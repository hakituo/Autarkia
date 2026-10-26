package com.aveline.ai.mobile.services.endpoint

import android.content.Context
import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.services.endpoint.resolver.ChannelPriority
import com.aveline.ai.mobile.services.endpoint.resolver.EndpointChannel
import com.aveline.ai.mobile.services.endpoint.resolver.EndpointProber
import com.aveline.ai.mobile.services.endpoint.resolver.NetworkTransportInspector
import com.aveline.ai.mobile.services.endpoint.resolver.NetworkWatcher
import com.aveline.ai.mobile.services.endpoint.resolver.ResolvedEndpoint
import com.aveline.ai.mobile.services.endpoint.resolver.channelOf
import com.aveline.ai.mobile.utils.BackendAddressRules
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.concurrent.atomic.AtomicLong
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 后端地址裁决器（薄壳门面）：在「局域网 / 组网 / 公网域名」之间自动选一个能用的。
 *
 * 解决的问题：后端同时监听 0.0.0.0:8000（局域网入口）、Tailscale 组网地址（点对点入口）
 * 和 Cloudflare Tunnel（公网入口），客户端不该让用户手动切换，而应
 * 「在家走局域网、出门走组网、组网不通再退公网」。
 *
 * 本类只做三件事：持有生效地址状态与广播、按优先级链裁决、对外提供触发入口。
 * 具体职责在 `resolver/` 子目录里，改哪一层就只动哪个文件：
 * - [EndpointProber]：探测某个地址是不是本项目后端；
 * - [NetworkTransportInspector]：链路类型判定 + 「局域网候选在当前网络下有没有可能直达」；
 * - [ChannelPriority]：候选排序判据（纯函数，有 host 单测）；
 * - [NetworkWatcher]：网络变化监听 + 去抖 + 周期重探；
 * - [BackendAddressRules]：地址分类（私网 / 组网 / 公网）与网段归属。
 *
 * 候选优先级：
 * - 手动锁定（AppPreferences.backendUrl 非空）—— 用户明确指定，不探测；
 * - 局域网（lanUrl）—— 仅当它**在本机当前网段内**（或拿不到网段信息）时才优先，
 *   否则排到最后兜底一次；
 * - 组网（vpnUrl）—— 远程通道里的优先项；
 * - 公网域名（tunnelUrl）—— 最后兜底。
 *
 * 组网与公网是**并存的两条远程通道**，不是互斥开关：手机开了 Tailscale 就走点对点直连
 * （不经公网边缘、无隧道抖动），没开或探不通时自动退到 Cloudflare 域名。
 *
 * **组网槽位留空 = 未启用该通道**：`vpnUrl` 默认是空串，[resolve] 会直接跳过这一档，
 * 绝不会去猜地址。地址来源有三个：设置页手填、槽位迁移时把已有组网地址升格进槽位、
 * 局域网发现时后端通过 UDP 信标自报（见 `ServerDiscoveryManager`）。
 *
 * **局域网候选的可行性判据是「本机接口网段是否覆盖它」，不是「有没有连 WiFi」**。
 * 这一条决定了「出门/换网络能不能自动切对」：
 * - 只按「有没有 WiFi 链路」判，在别人家的 WiFi、酒店/公司 WiFi、手机热点共享出来的
 *   网段上都会把家里的内网地址当成首选，白等一个 connect 超时，甚至（当远程通道槽位
 *   为空时）一直停在一个永远连不上的地址上，用户只能手动改地址；
 * - 按网段判，蜂窝数据、别人家 WiFi 都会直接跳过局域网候选，几十毫秒内落到远程通道；
 *   在家时本机地址就落在后端同一网段里，仍然优先走局域网，不会误绕公网。
 * 网段判据只是近似（跨网段路由、USB 网络共享、组网子网路由都可能让「网段对不上」的地址
 * 真的可达），所以它在 [resolve] 第 5 步仍保留一次兜底探测。
 *
 * 另外有一层物理兜底：当前生效地址是「本机当前网络到不了的私网地址」时（出门了、
 * 或在别处连了 WiFi 却还挂着家里的内网 IP），即使远程通道这次没探通（隧道冷启动、
 * 健康检查偶发慢）也强制切过去，否则一次探测抖动就会让用户整个出门期间都卡在内网地址上。
 * 同一条判据也用来决定「失败降级探测要不要绕过节流」——只按「是不是蜂窝」判的话，
 * 在别人家 WiFi 下（链路类型一直是 `wifi`）就会慢一拍。
 *
 * 裁决结果写进 AppPreferences.activeUrl，所有网络消费方统一读
 * AppPreferences.effectiveBackendUrl。
 *
 * 探测触发时机（五处）：
 * - App 启动（AvelineApplication.onCreate → [startMonitoring] 的初始回调）；
 * - 网络变化（[NetworkWatcher] 的默认网络与物理链路两层回调）；
 * - 连接失败降级（WebSocketManager / 聊天请求 → [resolveOnFailure]）；
 * - 设置页手动点「重新探测」；
 * - 周期重探（[NetworkWatcher] 的定时器，补上「组网从不可用变成可用」这类没有回调的事件）。
 */
@Singleton
class EndpointResolver @Inject constructor(
    @ApplicationContext private val context: Context,
    internal val appPreferences: AppPreferences
) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val inspector = NetworkTransportInspector(context)

    internal val prober = EndpointProber { appPreferences.accessToken }

    /** 网络监听交给 [NetworkWatcher]；它只在「有更优候选」时才让门面真的发探测请求。 */
    private val watcher = NetworkWatcher(
        scope = scope,
        inspector = inspector,
        periodicReprobeIntervalMs = PERIODIC_REPROBE_INTERVAL_MS,
        onResolve = { trigger -> resolve(trigger) },
        onPeriodicTick = { if (hasBetterCandidate()) resolve("周期重探") }
    )

    /**
     * 当前生效地址。初值取 [initialEndpoint]（≈ effectiveBackendUrl，但会跳过当前网络下
     * 物理上到不了的私网地址），让冷启动立刻按上次的结果连上，又不会在换了网络之后
     * 先往一个必然不通的局域网地址上撞一轮。
     */
    private val _active = MutableStateFlow(initialEndpoint())
    val active: StateFlow<ResolvedEndpoint> = _active.asStateFlow()

    private val _changes = MutableSharedFlow<String>(
        extraBufferCapacity = 8,
        onBufferOverflow = BufferOverflow.DROP_OLDEST
    )

    /** 生效地址发生变化的通知（新地址），供 WebSocketManager 强制重连。 */
    val changes: SharedFlow<String> = _changes.asSharedFlow()

    /** 串行化探测：并发探测会互相覆盖 activeUrl，也会把网络堆满。 */
    internal val resolveMutex = Mutex()

    /** 上次「失败降级」探测的时间戳，用于节流。 */
    private val lastFailureProbeAt = AtomicLong(0L)

    /**
     * 按优先级探测并采纳第一个可用候选。
     *
     * @param trigger 触发来源，只进日志，便于排查「为什么切到公网了」。
     * @return 本次裁决后的生效地址；**null 表示所有候选都不可达**（此时 [active] 仍保留
     *         原地址不变，避免把配置清成空）。调用方需要区分「探测成功」和「全都不通」
     *         时必须判 null，不能拿返回地址非空当成功 —— 全失败时返回的是沿用中的旧地址。
     */
    suspend fun resolve(trigger: String): ResolvedEndpoint? = resolveMutex.withLock {
        // 1. 手动锁定：用户明确指定，不做任何探测（也是「强制走公网测链路」的出口）
        val manual = appPreferences.backendUrl.trim()
        if (manual.isNotEmpty()) {
            return@withLock adopt(manual, EndpointChannel.MANUAL, trigger)
        }

        val lan = appPreferences.lanUrl.trim()
        val tunnel = appPreferences.tunnelUrl.trim()
        val vpn = appPreferences.vpnUrl.trim()
        // 局域网候选在当前网络下有没有可能直达。判据是「本机接口网段是否覆盖它」，
        // **不是「有没有连 WiFi」** —— 在别人家的 WiFi 上也是 WiFi，但网段对不上，
        // 后端地址根本不在那张网里，先探它只会白等一个 800ms 超时。
        val lanPlausible = lan.isNotEmpty() && inspector.isLanCandidatePlausible(lan)
        if (lan.isNotEmpty() && !lanPlausible) {
            // 明确记一条：这是「在家 / 在别处」判断出错的现场证据，
            // 没有它就只能靠猜「为什么这次没走局域网」。
            Log.i(TAG, "[$trigger] 局域网候选 $lan 在当前网络下不可达（网段不匹配或无局域网链路），跳过")
        }
        if (!lanPlausible && tunnel.isEmpty() && vpn.isEmpty()) {
            // 「开了流量 / 在别处连 WiFi 却切不过去」最常见的原因就是这个：远程通道槽位都是空的，
            // 根本没有可切的候选。打一条明确日志，免得每次都要翻代码才能确认。
            Log.w(TAG, "[$trigger] 局域网候选不可用，但未配置任何远程通道（tunnelUrl / vpnUrl 均为空）")
        }

        // 2. 局域网优先（仅当它在本机网段内、物理上有戏）。短超时，在家里几十毫秒就出结果。
        if (lanPlausible && prober.probe(lan, LAN_CONNECT_TIMEOUT_MS, LAN_READ_TIMEOUT_MS)) {
            return@withLock adopt(lan, EndpointChannel.LAN, trigger)
        }

        // 3. 组网通道（Tailscale 等点对点 VPN）。
        //    排在公网域名之前：两条都是「出门能用」的远程通道，但组网是手机直连电脑，
        //    不过公网边缘，既没有 Cloudflare 隧道的抖动/530，延迟也低得多。
        //    蜂窝下局域网候选已跳过，它实质就是第一候选。
        if (vpn.isNotEmpty() &&
            prober.probe(vpn, VPN_CONNECT_TIMEOUT_MS, VPN_READ_TIMEOUT_MS)
        ) {
            return@withLock adopt(vpn, EndpointChannel.VPN, trigger)
        }

        // 4. 公网兜底。组网没配或没探通时仍然可用；TLS 握手 + 边缘节点回源，超时给宽一些。
        if (tunnel.isNotEmpty() &&
            prober.probe(tunnel, WAN_CONNECT_TIMEOUT_MS, WAN_READ_TIMEOUT_MS)
        ) {
            return@withLock adopt(tunnel, EndpointChannel.TUNNEL, trigger)
        }

        // 5. 远程候选都不通时，最后再试一次局域网。
        //    网段判据只是「物理上有没有戏」的近似：跨网段路由（家里 WiFi 与有线分成两个网段
        //    但互通）、USB 网络共享、组网子网路由，都能让「网段对不上」的地址真的可达。
        //    放在最后而不是最前，是为了让这些少数派场景仍然连得上，同时不拖慢主流场景
        //    （蜂窝 / 在别处连 WiFi 时，先探局域网就是白等一个 800ms 超时）。
        if (!lanPlausible && lan.isNotEmpty() &&
            prober.probe(lan, LAN_CONNECT_TIMEOUT_MS, LAN_READ_TIMEOUT_MS)
        ) {
            return@withLock adopt(lan, EndpointChannel.LAN, trigger)
        }

        // 6. 全都不通时的物理兜底。
        //    当前生效地址是「本机当前网络到不了的私网地址」时（典型：出门了，或者在外面连了
        //    别人家的 WiFi，生效地址还挂着家里的内网 IP），哪怕远程通道这次也没探通，也要切过去：
        //    留在这个地址上是 100% 发不出消息的，而远程通道只是「这次没探通」
        //    （隧道冷启动、健康检查偶发超时都可能导致）。
        //    少了这一步，一次探测抖动就会让用户整个出门期间都卡在内网地址上。
        val activeUrl = _active.value.url
        val activeImpossible = activeUrl.isNotEmpty() &&
            BackendAddressRules.isLanOnlyHost(activeUrl) &&
            !inspector.isLanCandidatePlausible(activeUrl)
        if (activeImpossible) {
            // 组网优先于公网：两条都能出公网，先挑更稳的那条；没配组网才退到公网域名。
            val remoteUrl = vpn.ifEmpty { tunnel }
            if (remoteUrl.isNotEmpty()) {
                Log.w(TAG, "[$trigger] 当前生效地址 $activeUrl 在本机网段内不可达，强制降级远程通道: $remoteUrl")
                return@withLock adopt(
                    remoteUrl,
                    if (vpn.isNotEmpty()) EndpointChannel.VPN else EndpointChannel.TUNNEL,
                    "$trigger(强制降级)"
                )
            }
        }

        // 全都不通：沿用原地址（不能把配置清成空），但把「这次是不通的」标出来，
        // 界面才不会继续把它显示成一切正常。
        Log.w(TAG, "[$trigger] 所有候选均不可达，沿用当前地址: $activeUrl")
        _active.value = _active.value.copy(reachable = false)
        null
    }

    /**
     * 请求 / WebSocket 连接失败后的降级探测。
     *
     * 候选顺序与 [resolve] 一致（随网络类型变化），所以两个方向都覆盖：
     * 出门时局域网失效 → 降到公网；回家后 WiFi 恢复 → 换回局域网。
     *
     * 与 [resolve] 的区别是节流：失败回调在重连期间可能密集触发，
     * 没有间隔限制的话每次失败都串一遍完整探测（含一次必然超时的局域网探测），
     * 白白耗电。节流窗口内直接跳过（返回 null）。
     *
     * 例外：「当前地址在物理上不可能通」时不受节流限制 —— 判据是
     * [NetworkTransportInspector.isLanCandidatePlausible]：当前生效地址是私网地址，
     * 而本机接口网段里根本没有它。蜂窝数据下（还挂着家里的内网 IP）和**在别处连了 WiFi**
     * （网段对不上）两种情况都算紧急。
     *
     * 后者尤其要紧：那种状态下链路类型一直是 `wifi`，若只按「是不是蜂窝」判紧急，
     * 用户会卡在连不上的内网地址上一直等到节流窗口结束才被换掉。
     *
     * @return 裁决结果；null 表示本次被节流跳过或所有候选都不可达
     */
    suspend fun resolveOnFailure(): ResolvedEndpoint? {
        val current = _active.value.url
        val urgent = current.isNotEmpty() &&
            BackendAddressRules.isLanOnlyHost(current) &&
            !inspector.isLanCandidatePlausible(current)
        if (!urgent) {
            val now = System.currentTimeMillis()
            val last = lastFailureProbeAt.get()
            if (now - last < FAILURE_PROBE_MIN_INTERVAL_MS) return null
            if (!lastFailureProbeAt.compareAndSet(last, now)) return null
        } else {
            // 紧急重探也要更新时间戳，避免紧接着的普通失败再探一次。
            lastFailureProbeAt.set(System.currentTimeMillis())
        }
        return resolve("失败降级")
    }

    /**
     * 开始监听网络变化并触发重探测。幂等，重复调用无副作用。
     *
     * 放在 Application 而不是只在 Activity 里调用，是为了兜住「界面还没打开」的场景
     * （开机自启、被推送唤醒、服务先于界面启动），否则那段时间会一直用着上次的旧通道。
     */
    fun startMonitoring() {
        watcher.start()
    }

    /** 门面只做参数收集，判据在 [ChannelPriority]（纯函数，有 host 单测）。 */
    private fun hasBetterCandidate(): Boolean = ChannelPriority.hasBetterCandidate(
        current = _active.value.channel,
        // 「局域网候选现在有没有可能直达」—— 判据是网段是否覆盖（见 inspector），
        // 不是「有没有连 WiFi」：在别人家的 WiFi 上也是 WiFi，但那个地址在那张网里不存在。
        lanPossible = appPreferences.lanUrl.trim()
            .let { it.isNotEmpty() && inspector.isLanCandidatePlausible(it) },
        lanUrl = appPreferences.lanUrl.trim(),
        vpnUrl = appPreferences.vpnUrl.trim(),
        tunnelUrl = appPreferences.tunnelUrl.trim()
    )

    /** 采纳一个候选：落盘 + 更新状态 + 地址真变了才广播。 */
    private fun adopt(url: String, source: EndpointChannel, trigger: String): ResolvedEndpoint {
        val previous = _active.value
        // 通道按**地址本身**判定，不按「来自哪个槽位」：局域网槽位里被填进一个公网域名
        // （手填 / 导入设置 / 旧版本迁移都可能）时，若照槽位命名，设置页会把「正在走公网域名」
        // 显示成「当前通道：局域网」，用户就没法从界面上判断自己到底靠什么在连。
        val channel = channelOf(url, manualLocked = source == EndpointChannel.MANUAL)
        // reachable = true：能走到这里就说明它刚被探通（或用户手动锁定），
        // 顺手把上一次「全都不通」留下的标记清掉。
        val endpoint = ResolvedEndpoint(url, channel, reachable = true)

        // 先落盘再广播：订阅者收到通知后会立刻读 effectiveBackendUrl，
        // 此时 activeUrl 必须已经是新值，否则会拿旧地址去重连。
        appPreferences.activeUrl = url
        _active.value = endpoint

        if (previous.url != url) {
            Log.i(TAG, "[$trigger] 通道切换 ${previous.channel}(${previous.url}) -> $channel($url)")
            _changes.tryEmit(url)
        } else {
            Log.d(TAG, "[$trigger] 通道确认 $channel($url)")
        }
        return endpoint
    }

    /**
     * 冷启动初值：进程刚起、还没裁决之前生效的地址与通道。
     *
     * 通道同样按**地址本身**判定（见 [channelOf]），所以「手动锁定填了域名」时界面从第一帧
     * 就显示「手动锁定」，不必等一次裁决跑完才纠正 —— 少了这一步，界面会先显示上一次裁决
     * 的旧通道，看起来就像「我填的地址没生效」。
     */
    private fun initialEndpoint(): ResolvedEndpoint {
        val url = initialUrl()
        return ResolvedEndpoint(
            url = url,
            channel = channelOf(url, manualLocked = appPreferences.backendUrl.trim().isNotEmpty())
        )
    }

    /**
     * 冷启动初值：进程刚起、还没裁决之前，先用哪个地址发请求。
     *
     * 顺序与 [AppPreferences.effectiveBackendUrl] 的兜底链一致（手动锁定 > 裁决结果 >
     * 局域网 > 组网 > 公网），**但会跳过「当前网络下物理上到不了」的私网地址**。
     *
     * 为什么不能直接照抄兜底链：上次在家裁决出的 activeUrl 就是局域网地址，出门/换了
     * 网络后它被持久化下来，冷启动时会先拿它去发一轮必然失败的请求（用户体感就是
     * 「WiFi 都没开、人在外面，却还在往一个局域网地址上连」），要等第一次裁决跑完才纠正。
     * 这里直接退到远程候选，把那一轮白等省掉；真的在家时本机网段仍然覆盖那个局域网地址，
     * 它会照旧被优先命中。
     */
    private fun initialUrl(): String {
        val manual = appPreferences.backendUrl.trim()
        if (manual.isNotEmpty()) return manual

        val active = appPreferences.activeUrl.trim()
        if (active.isNotEmpty() && !isPhysicallyUnreachable(active)) return active

        val candidates = listOf(appPreferences.lanUrl, appPreferences.vpnUrl, appPreferences.tunnelUrl)
            .map { it.trim() }
            .filter { it.isNotEmpty() }
        candidates.firstOrNull { !isPhysicallyUnreachable(it) }?.let { return it }

        // 全都不可能（或压根没配）时保留原值：宁可拿旧地址试一次，也不要把配置清成空。
        return (listOf(active) + candidates).firstOrNull { it.isNotEmpty() }.orEmpty()
    }

    /** 私网地址 + 本机当前网段里没有它 = 这一轮请求必然发不出去。 */
    private fun isPhysicallyUnreachable(url: String): Boolean =
        BackendAddressRules.isLanOnlyHost(url) && !inspector.isLanCandidatePlausible(url)

    companion object {
        private const val TAG = "EndpointResolver"

        /**
         * 局域网探测超时。**必须短**：出门在外时局域网候选是必然连不上的，
         * 超时多长，用户就要多等多久才能降到公网。局域网正常应在 100ms 内返回。
         */
        internal const val LAN_CONNECT_TIMEOUT_MS = 800
        internal const val LAN_READ_TIMEOUT_MS = 800

        /**
         * 组网通道探测超时：Tailscale 打洞成功时是几十毫秒的直连，走 DERP 中继多一跳
         * 也就几百毫秒，1.5s 富余。
         *
         * 比公网（3s）短是刻意的：手机端没开 Tailscale 时，100.x 地址在蜂窝网络下不可达，
         * 连接会一直挂到超时才转公网候选。这段等待是用户能感知的「切换卡顿」，能短就短。
         */
        internal const val VPN_CONNECT_TIMEOUT_MS = 1500
        internal const val VPN_READ_TIMEOUT_MS = 1500

        /** 公网探测超时：TLS 握手 + Cloudflare 边缘回源，需要给宽一些。 */
        internal const val WAN_CONNECT_TIMEOUT_MS = 3000
        internal const val WAN_READ_TIMEOUT_MS = 3000

        /** 「失败降级」探测的最小间隔，避免重连风暴把探测打成高频任务。 */
        private const val FAILURE_PROBE_MIN_INTERVAL_MS = 20_000L

        /**
         * 周期重探间隔。5 分钟是权衡：够短，走到半路就能自动升回组网；
         * 够长，不会把探测打成高频任务（且只在有更优候选时才真的探测）。
         */
        private const val PERIODIC_REPROBE_INTERVAL_MS = 5 * 60 * 1000L
    }
}
