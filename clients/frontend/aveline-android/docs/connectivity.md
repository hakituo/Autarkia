# 后端通道（局域网 → 组网 → 公网）与服务器发现

> Android 端子文档 · 上级入口：[README.md](../README.md)
> 只写当前实现；改代码前先看 `.trae/context/routing/android.md` 定位文件。

---

后端同时监听 `0.0.0.0:8000`（局域网入口）、Tailscale 组网地址（点对点入口）
和 Cloudflare Tunnel（公网入口），客户端**不再让用户手动切换**，
而是由 `EndpointResolver` 按「本机网段 + 真实探测」自动裁决：

```
手动锁定（AppPreferences.backendUrl，非空即生效，不探测）
  > 局域网（AppPreferences.lanUrl，短超时 800ms 探测）—— 仅当它在本机当前网段内
    > 组网（AppPreferences.vpnUrl，1.5s 探测）—— 组网与公网是并存的两条远程通道
      > 公网域名（AppPreferences.tunnelUrl，宽松超时 3s 探测）
```

**局域网候选的可行性判据是「本机接口网段是否覆盖它」，不是「有没有连 WiFi」**
（`NetworkTransportInspector.isLanCandidatePlausible()`）。判据必须是网段，因为
「连了 WiFi」和「能到家里那台后端」是两件不同的事：

- 蜂窝数据、**别人家的 WiFi / 酒店 / 公司 WiFi**：网段对不上，后端地址根本不在那张网里。
  跳过局域网候选后直接落到组网/公网，不再白等一个 800ms 超时，也不会停在一个
  永远连不上的内网地址上；
- 在家（WiFi 或网线）：本机地址就落在后端同一网段里，仍然优先走局域网，不会误绕公网；
- 开着 Tailscale 时也成立：默认网络是那条 VPN，底层 WiFi 的网段从「网络回调快照」里取回来。

网段判据只是「物理上有没有戏」的近似（跨网段路由、USB 网络共享、组网子网路由都能让
「网段对不上」的地址真的可达），所以它在所有远程候选都不通时仍会**最后再补探一次**
局域网候选；反过来，只有真探通了才会被采纳。所以实际效果是：
在家走局域网，出门走组网，组网不通（`vpnUrl` 没配、手机没开 Tailscale、电脑关机）才退公网域名。

**组网与公网不是互斥开关**：`vpnUrl` 是手机直连电脑的点对点通道，不经公网边缘，
没有 Cloudflare 隧道的抖动与偶发 530；`tunnelUrl` 保留作兜底，两条都配着最稳。
只配其中一条也完全可用 —— 不配 `vpnUrl` 时行为与加这个槽位之前完全一致。

裁决结果写进 `AppPreferences.activeUrl`，所有网络消费方统一读
`AppPreferences.effectiveBackendUrl`（REST 拦截器 / `WebSocketManager` /
`MediaUrlResolver` / `FileUploadManager`）。冷启动探测还没跑完时，
`effectiveBackendUrl` 按「手动锁定 > 上次裁决结果 > 局域网 > 组网 > 公网」兜底，
而 `EndpointResolver` 的初值会**跳过当前网络下物理上到不了的私网地址**
（典型：在家用过的局域网地址被持久化下来，出门冷启动时不该先往它上面撞一轮）。

> **判据陷阱**：Tailscale 用的是 CGNAT 段 `100.64.0.0/10`，外观像私网但蜂窝下可达。
> `BackendAddressRules.isLanOnlyHost()` 必须对它返回 `false`，否则兜底逻辑会在出门时
> 把生效地址从组网强制切走。`BackendAddressRulesTest` 有单测钉住这一点。

> **VPN 会骗过 `activeNetwork`**：手机开着 Tailscale 时 `activeNetwork` 是那条 VPN 网络
> （只有 `TRANSPORT_VPN`），只看默认网络会误判成「没有局域网链路」，人在家也绕走远程通道。
> 所以 `NetworkTransportInspector.hasLanTransport()`（链路层判据）与
> `isLanCandidatePlausible()`（网段判据）在默认网络没命中时都会查内部网络快照
> （注册一次 `registerNetworkCallback` 常驻维护；`getAllNetworks()` 在 API 31 起已废弃）
> 把底层 WiFi / 以太网找回来。

> **网段证据只认 WiFi / 以太网链路，且跳过 `/32`**：蜂窝的 `10.x/30`（运营商大内网）和
> VPN 的 `100.x/32` 不代表「我在哪张局域网」，企业 / 校园 WiFi 下发的 `/32` 主机路由也不携带
> 网段信息。这类情况下判「不知道」并回退到链路层判据（宁可多探一次），
> 而不是拿它判「不在同一张网」（会误伤「在家却连不上局域网」）。


**探测触发时机**（五处）：

1. 进程启动 —— `AvelineApplication` 调 `EndpointResolver.startMonitoring()`，
   两层回调注册时都会立刻各回调一次当前网络；
2. 网络变化 —— `NetworkWatcher` 的**两层**回调，去抖后重探：
   - 默认网络回调（`onAvailable` / `onCapabilitiesChanged` / `onLost`）负责「默认网络换没换、
     链路类型变没变」；
   - 物理链路回调（请求式，WiFi / 蜂窝 / 以太网）负责「底层链路来没来、走没走」。
     少了这层会漏掉一整类切换：开着 Tailscale 时默认网络恒为那条 VPN 网络、transport 恒为
     `other`，WiFi ↔ 蜂窝 的交接被上面那层的去重挡掉，通道永远不重选；
3. 连接失败降级 —— `WebSocketManager.scheduleReconnect()` 从第二次重连起问一次
   `resolveOnFailure()`（20 秒节流），避免在死通道上无限重连；
4. 设置页手动点「重新探测」；
5. 周期重探 —— `NetworkWatcher` 每 5 分钟过一遍 `ChannelPriority.hasBetterCandidate()`，
   只在「存在更优候选」时才真的探测。

> **为什么需要第 5 条**：事件型触发都靠 `ConnectivityManager` 回调，而「Tailscale 连上了 /
> 打洞完成了」**不产生任何回调** —— 默认网络一直是那条 VPN 网络，`transportOf()` 恒为 `other`，
> 被 `onCapabilitiesChanged` 的去重挡掉。少了周期重探，一次「组网还没就绪就探失败」的抖动就会
> 让用户整个外出期间挂在公网域名上：公网一直好用 → WebSocket 不失败 → `resolveOnFailure()`
> 也不会被调用，通道再也升不回组网。

**探测必须做对的三件事**（见 `EndpointProber.probe()`）：

- 走裸 `HttpURLConnection`，**不能复用业务 OkHttpClient** —— 后者挂了
  `baseUrlInterceptor`，会把地址重写成当前生效地址，探测就变成自己测自己；
- **带访问令牌** —— `/api/v1/health` 在 `is_protected_path` 名单里，无令牌会被 401/503 拒掉；
- **校验响应体的服务标识** —— 端口通不等于后端，局域网里任意开 8000 的设备都能连通。

**代码结构**：门面 `EndpointResolver` 只持有生效地址状态、按优先级链裁决、对外提供触发入口；
具体职责拆在 `services/endpoint/resolver/` 子目录里，改哪一层就只动哪个文件：

| 文件 | 职责 |
| --- | --- |
| `EndpointChannel.kt` | `EndpointChannel` 枚举 + `ResolvedEndpoint` 数据类（含「这次裁决通不通」，跨子模块共享，不嵌在门面里） |
| `EndpointProber.kt` | 探测某地址是不是本项目后端（裸连接 + 令牌 + 响应体身份校验 + 兜底超时） |
| `NetworkTransportInspector.kt` | 链路类型判定 + 「局域网候选在当前网络下有没有可能直达」（含「开 VPN 时也找回底层 WiFi」） |
| `ChannelPriority.kt` | 候选排序判据（纯函数，`ChannelPriorityTest` 钉住） |
| `NetworkWatcher.kt` | 两层网络回调 + 去抖 + 周期重探 |

**地址判据收敛在 `BackendAddressRules`**（纯函数，可直接跑 JVM 单测）：私网 / 组网 / 公网
三类互斥。Tailscale 用的 CGNAT 段 `100.64.0.0/10` **既不是私网也不是普通公网** ——
判成私网会让「蜂窝 + 私网就强制降级」的兜底把组网地址一起切走，判成公网则让「出门时组网优先于
公网」的排序失去依据。另外 `isPrivateIpv4()` / `isHostCoveredBy()` 提供网段归属判断
（`/0` 默认路由刻意不参与判定，否则 VPN 拆出来的 `0.0.0.0/1` + `128.0.0.0/1`
会把任意地址都判成「可达」）。

**地址槽位迁移**（`AppPreferences`，两步一次性迁移）：

- **V2** `migrateToDualEndpointIfNeeded()`：把旧的「单一 backendUrl + 手动 Tunnel 开关」
  迁移成多槽位（旧 `lanUrlBackup` → `lanUrl`，旧 `backendUrl` → `activeUrl` 缓存）；
  旧地址若落在组网段则一并认进 `vpnUrl`；
- **V3** `promoteVpnSlotIfNeeded()`：`vpnUrl` 为空时，把「手动锁定 / 上次裁决结果」里的组网
  地址**复制**进 `vpnUrl` 槽位（不碰手动锁定本身）。

> **组网槽位留空 = 未启用这条通道**：`vpnUrl` 默认空串，`EndpointResolver` 会直接跳过这一档，
> 绝不会去猜地址。老用户里有一批人把 Tailscale 的 100.x 填在「手动锁定」里用，升级后就会
> 出现「明明开着组网却一直走公网域名」—— V3 就是补这个洞。想切到自动模式，把「手动锁定」
> 那格清空即可。

组网槽位一共有三个来源：**设置页手填**、**V3 迁移升格**、**UDP 信标自报**（见下节）。

### 设置页「当前通道」的展示口径

三件事都必须成立，否则用户无法从界面上判断自己到底靠什么在连（这三条都是实测踩出来的）：

1. **通道按地址本身判定**（`channelOf()`，纯函数有单测），**不是按「来自哪个槽位」**。
   槽位是可以被填错的 —— 局域网槽位里放一个公网域名（手填 / 导入设置 / 旧版本迁移），
   照槽位命名就会把「正在走公网域名」显示成「当前通道：局域网」；
2. **手动锁定槽位非空时，展示就以它为准**（它本来就是 `effectiveBackendUrl` 的第一优先级），
   与裁决器上一次裁决的结果无关。否则会出现「请求已经走新地址了，界面还停在旧通道上」；
3. **候选全都不通时要显示「（不可达）」**：裁决器会沿用原地址（不把配置清成空），
   但那个地址此刻是连不上的，不该继续显示成一切正常。

另外输入框的内容**不会自动生效**：手动锁定槽位只在点「保存」时落盘，另外三个槽位虽然
边打字边落盘，也要等一次重新裁决（改动后 600ms 去抖重探）才会被采纳；而「测试连接」测的
一律是**已保存**的地址。所以只要输入框里的值和已保存的不一致，界面就会显示
「有修改还没保存」—— 少了这句提示，用户填完域名看到的仍是上一次裁决的通道（比如「局域网」），
只会得出「填了没用」的结论。

### 服务器零配置发现

`ServerDiscoveryManager` 实现三层发现策略：

1. 已配的局域网地址仍可用就直接用（省掉一次广播等待）
2. UDP 广播发现（端口 28899，5 秒超时）
3. 网段扫描兜底（9 个常见子网）

发现结果写入 `AppPreferences.lanUrl` **槽位**（不是 `backendUrl`），是否采用交给
`EndpointResolver` 按优先级裁决。旧实现「用户配过地址就不覆盖」会让设了公网域名后
永远切不回局域网，现在不再有这个限制。

**信标载荷同时带后端的组网地址**（可选段），客户端据此把 `vpnUrl` 槽位自动填上 ——
否则用户得自己从电脑上抄一个 `100.x` 地址填进设置页，而这正是「开着组网却走公网」最常见的成因：

```
后端 core/services/discovery/udp_beacon.py:
  AVELINE_SERVER|http://<局域网IP>:<port>[|http://<组网IP>:<port>]

客户端 services/discovery/BeaconPayload.kt: BeaconPayload.parse()
```

两侧是一对**线上契约**，各有单测钉住（`tests/unit/test_discovery_udp_beacon.py` /
`BeaconPayloadTest`）。第三段缺失即「后端没有组网入口」，不是「信标没发全」。

> **为什么只在局域网里问得到**：信标是局域网广播，手机出门切蜂窝后收不到。所以补槽位的
> 时机只能是「在家这次发现」—— 组网槽位为空时会跳过「已配局域网地址仍可用」的快速路径，
> 多听一遍广播（最多 5 秒，且在 `MainActivity` 的后台协程里，不阻塞界面）。
> 补上之后该快速路径恢复，这个额外等待只发生一次。

> **组网地址不做身份校验，局域网地址必须做**：信标是明文 UDP，局域网里谁都能伪造。
> 但组网地址只是**候选** —— 真正采纳前要过 `EndpointResolver` 的探测（HTTP 200 +
> 响应体含服务标识 + 令牌），伪造一个假地址最多让探测白跑 1.5 秒，劫持不了连接。
> 反过来在这里做校验会导致「手机当前没开组网 → 探测必然失败 → 槽位永远填不上」，
> 正好错过唯一能问到地址的时机。

> 身份校验走 `/api/v1/health` 并携带访问令牌。旧实现请求的是裸 `/health` 且不带令牌，
> 后端既没有该路由、该路径又需要认证，所以自动发现实际上从未成功过。

> **链路判定不要另写一份**：`ServerDiscoveryManager` 曾自带一份只查默认网络的
> `hasLanTransport()`，开着 Tailscale 时默认网络是 VPN 网络，于是「在家也判定为非局域网链路」
> → 直接跳过整轮发现。现在统一用 `NetworkTransportInspector`。
