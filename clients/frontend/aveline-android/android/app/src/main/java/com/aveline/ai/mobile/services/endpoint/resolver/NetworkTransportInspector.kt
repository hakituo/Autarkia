package com.aveline.ai.mobile.services.endpoint.resolver

import android.content.Context
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import com.aveline.ai.mobile.utils.BackendAddressRules
import java.net.Inet4Address

/**
 * 链路类型判定：把一份 [NetworkCapabilities] 归成传输类型，并回答
 * 「设备现在能不能到某个局域网后端地址」。
 *
 * 只表达「这条网络自己是什么」与「局域网候选有没有可能直达」两件事，不碰候选排序，
 * 也不碰地址槽位 —— 那些是 [ChannelPriority] 与门面的事。
 *
 * **为什么不能只看「有没有连 WiFi」**（这是本类最要紧的一条）：
 * 「连了 WiFi」和「能到家里那台后端」是两件不同的事。别人家的 WiFi、酒店/公司 WiFi、
 * 手机热点共享出来的网段，全都是 WiFi，但后端地址在那些网段上根本不存在。反过来，
 * 蜂窝 + USB 网络共享、蜂窝 + 组网子网路由，也可能真的能到内网地址。
 * 所以判据取「**本机接口网段是否覆盖后端地址**」：它同时覆盖上面两种错判方向，
 * 而链路类型只留给 [ChannelPriority] 做排序与超时参考。
 */
internal class NetworkTransportInspector(private val context: Context) {

    /** WiFi / 以太网链路的快照，由 [trackingCallback] 持续维护（见 [ensureTracking]）。 */
    private val snapshot = NetworkSnapshot()

    /** 回调是否已注册。注册失败会复位，下次查询再试。 */
    @Volatile
    private var tracking = false

    private val trackingLock = Any()

    private val networkRequest = NetworkRequest.Builder()
        .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
        .addTransportType(NetworkCapabilities.TRANSPORT_ETHERNET)
        .build()

    /**
     * 网络清单的维护者：`ConnectivityManager.getAllNetworks()` 在 API 31 起已废弃
     * （官方替代就是 [ConnectivityManager.registerNetworkCallback]），这里注册一次、
     * 常驻进程，把「当前有哪些 WiFi / 以太网链路」存进 [snapshot]。
     *
     * 注册后系统会为每个**当前已存在**的匹配网络回调一次 [onAvailable]，
     * 所以快照不必等下一次网络变化才可用；[onAvailable] 里主动把能力与链路信息拉全，
     * 不依赖后续的 Changed 回调。
     */
    private val trackingCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            val cm = connectivityManager() ?: return
            cm.getNetworkCapabilities(network)?.let { snapshot.putCapabilities(network, it) }
            cm.getLinkProperties(network)?.let { snapshot.putLinkProperties(network, it) }
        }

        override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
            snapshot.putCapabilities(network, caps)
        }

        override fun onLinkPropertiesChanged(network: Network, linkProperties: LinkProperties) {
            snapshot.putLinkProperties(network, linkProperties)
        }

        override fun onLost(network: Network) {
            snapshot.remove(network)
        }
    }

    init {
        // 尽早注册：只在查询时注册的话，冷启动第一次裁决可能读到一个空快照。
        connectivityManager()?.let { ensureTracking(it) }
    }

    /**
     * 把一份网络能力归成传输类型字符串。
     *
     * 蜂窝即使一直连着，只要默认网络是 WiFi，局域网候选就仍然值得优先探。
     * VPN / 蓝牙共享等一律归到 `other`：它们不是「能到局域网」的判据，
     * 但在 [NetworkWatcher] 里仍算一次传输类型变化，会触发重探。
     */
    fun transportOf(caps: NetworkCapabilities?): String {
        if (caps == null) return TRANSPORT_NONE
        return when {
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> TRANSPORT_WIFI
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> TRANSPORT_ETHERNET
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> TRANSPORT_CELLULAR
            else -> TRANSPORT_OTHER
        }
    }

    /** 给定网络的能力是不是「能到局域网」的 WiFi / 以太网。 */
    fun isLanTransport(caps: NetworkCapabilities?): Boolean {
        val transport = transportOf(caps)
        return transport == TRANSPORT_WIFI || transport == TRANSPORT_ETHERNET
    }

    /**
     * 当前设备有没有可能访问局域网后端（WiFi / 有线；只有蜂窝一律认为没有）。
     *
     * **不能只看 activeNetwork**：手机开着 Tailscale / 任意 VPN 时，`activeNetwork` 会是
     * 那条 VPN 网络，它的 capabilities 只有 `TRANSPORT_VPN`，[transportOf] 落到
     * `TRANSPORT_OTHER` → 只盯着默认网络的话会判成「没有局域网链路」，
     * 结果是**人在家里 WiFi 下、却绕走远程通道**（组网或公网域名）。
     * 这在加了组网槽位后从「无所谓」变成「天天发生」：Tailscale 是常开的。
     *
     * 所以先看默认网络（绝大多数情况一步出结果），没命中再查 [snapshot] ——
     * 它是注册网络回调时收回来的底层 WiFi / 以太网（VPN 并不会让底层网络消失，
     * 它只是不再当默认网络）。
     *
     * 反过来也成立：蜂窝 + VPN 时快照里没有 WiFi 链路，仍然判 false，
     * 出门该走远程通道还是走远程通道。
     *
     * **这条判据只回答「链路层像不像局域网」**，不回答「能不能到某个具体地址」——
     * 后者用 [isLanCandidatePlausible]。这里保留它有两个用途：给
     * `ServerDiscoveryManager` 判断「值不值得做局域网发现」，以及给
     * [isLanCandidatePlausible] 在拿不到链路信息时兜底。
     */
    fun hasLanTransport(): Boolean {
        val cm = connectivityManager() ?: return false
        if (isLanTransport(cm.getNetworkCapabilities(cm.activeNetwork))) return true
        ensureTracking(cm)
        return snapshot.read().any { isLanTransport(it.capabilities) }
    }

    /**
     * 这个候选地址**在当前网络下有没有可能直达**。用来决定「值不值得花一个探测超时去试」，
     * 以及「已经生效的地址是不是已经物理上不可能通了」。
     *
     * 判据分三种情况：
     * 1. 地址是**私网 IPv4 字面量**（`192.168.x.x` / `10.x` / `172.16-31.x`）→
     *    看它是否落在 [localLanCidrs]（本机所在局域网的网段）里。
     *    落在里面 = 同一张网，值得探；落不进去 = 这个地址只可能存在于另一张网，
     *    探也是白等一个超时（**在别人家的 WiFi 上就是这种情况**）。
     * 2. 地址是**域名 / 公网 IP / 组网段**（`100.64.0.0/10`）→ 无法用网段判断
     *    （域名要先解析，组网地址根本不在本机网段里），回退到 [hasLanTransport]：
     *    有局域网链路就仍然值得一试。
     * 3. **拿不到任何局域网网段**（IPv6-only、WiFi 下发 /32 主机路由、系统服务异常）
     *    → 同样回退到 [hasLanTransport]，宁可多探一次也不要漏掉「在家却连不上局域网」。
     *
     * 判 true 不等于一定通（WiFi 连着但没连上路由、后端没开机），只是「物理上有戏」；
     * 真正采纳仍然必须过 [EndpointProber] 的探测。判 false 也不绝对 —— 跨网段路由
     * （家里 WiFi 与有线分成两个网段但互通、组网子网路由）确实存在，所以门面在
     * 「所有远程候选都不通」时仍会最后再试一次局域网候选，见 `EndpointResolver.resolve`。
     */
    fun isLanCandidatePlausible(rawUrl: String): Boolean {
        val host = BackendAddressRules.hostOf(rawUrl)
        if (host.isEmpty()) return false
        if (!BackendAddressRules.isPrivateIpv4(host)) return hasLanTransport()
        val cidrs = localLanCidrs()
        if (cidrs.isEmpty()) return hasLanTransport()
        return BackendAddressRules.isHostCoveredBy(host, cidrs)
    }

    /**
     * 本机当前所在**局域网**的网段（`"192.0.2.50/24"` 形式），跨全部网络收集。
     *
     * 三个取舍，每一个都对应一类误判：
     *
     * 1. 只取 `LinkProperties.linkAddresses`（接口自己的地址 + 前缀），**刻意不看路由表**：
     *    默认路由（`0.0.0.0/0`，或 VPN 拆出来的 `0.0.0.0/1` + `128.0.0.0/1`）会把**任意**地址
     *    都算成「已路由」，判据就废了；而且「包被发出去」不等于「能到」。
     * 2. **只认 WiFi / 以太网链路**：蜂窝的 `10.x/30`、VPN 的 `100.x/32` 不代表局域网的网段，
     *    把它们算进来会让「我在哪张网」这个判断失去意义（运营商大内网也是 10.x）。
     * 3. **跳过 `/32`**：那是主机路由，不携带网段信息（企业 / 校园 WiFi 会这样下发）。
     *    宁可判「不知道」（上层回退到 [hasLanTransport]），也不要拿它判「不在同一张网」。
     *
     * 必须跨全部 WiFi / 以太网链路而不是只看默认网络：开着 Tailscale 时默认网络是那条 VPN，
     * 底层 WiFi 只存在于 [snapshot] 里，而它才是「在家」的凭据。
     */
    private fun localLanCidrs(): List<String> {
        val cm = connectivityManager() ?: return emptyList()
        ensureTracking(cm)
        return snapshot.read().flatMap { entry ->
            if (!isLanTransport(entry.capabilities)) return@flatMap emptyList()
            val linkProperties = entry.linkProperties ?: return@flatMap emptyList()
            linkProperties.linkAddresses.mapNotNull { link ->
                val address = link.address as? Inet4Address ?: return@mapNotNull null
                if (link.prefixLength >= HOST_ROUTE_PREFIX) return@mapNotNull null
                val literal = address.hostAddress ?: return@mapNotNull null
                if (!BackendAddressRules.isPrivateIpv4(literal)) return@mapNotNull null
                "$literal/${link.prefixLength}"
            }
        }.distinct()
    }

    /**
     * 注册一次网络回调，之后靠它维护 [snapshot]。
     *
     * 幂等：查询路径每次都会调用，用 [tracking] 挡重复注册；注册失败（系统服务异常、
     * 权限缺失）时复位标志，下次查询再试 —— 失败期间查询退化为「只看默认网络」，
     * 不会把异常抛给调用方。
     */
    private fun ensureTracking(cm: ConnectivityManager) {
        if (tracking) return
        synchronized(trackingLock) {
            if (tracking) return
            tracking = runCatching {
                cm.registerNetworkCallback(networkRequest, trackingCallback)
            }.isSuccess
        }
    }

    /** 取 ConnectivityManager；拿不到返回 null（权限缺失或系统服务异常）。 */
    fun connectivityManager(): ConnectivityManager? = context.applicationContext
        .getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager

    companion object {
        const val TRANSPORT_WIFI = "wifi"
        const val TRANSPORT_ETHERNET = "ethernet"
        const val TRANSPORT_CELLULAR = "cellular"
        const val TRANSPORT_OTHER = "other"
        const val TRANSPORT_NONE = "none"

        /** 主机路由前缀（`/32`）：只描述一台主机，不携带「我在哪张网」的信息。 */
        private const val HOST_ROUTE_PREFIX = 32
    }
}

/**
 * 「网络 → 能力 / 链路信息」快照，替代已废弃的 `ConnectivityManager.getAllNetworks()`。
 *
 * 写入来自 [NetworkTransportInspector] 注册的网络回调（系统回调线程），读取来自调用方
 * 线程，读写都用同一把锁圈住；条目数是链路条数（个位数），不存在争用问题。
 *
 * 两个字段都允许为 null：能力与链路信息由不同的回调分别送达，先到的那一半先入账，
 * 调用方按「拿不到就跳过」处理。
 */
private class NetworkSnapshot {

    private val lock = Any()
    private val entries = LinkedHashMap<Network, NetworkSnapshotEntry>()

    fun putCapabilities(network: Network, capabilities: NetworkCapabilities) {
        synchronized(lock) {
            entries[network] = NetworkSnapshotEntry(capabilities, entries[network]?.linkProperties)
        }
    }

    fun putLinkProperties(network: Network, linkProperties: LinkProperties) {
        synchronized(lock) {
            entries[network] = NetworkSnapshotEntry(entries[network]?.capabilities, linkProperties)
        }
    }

    fun remove(network: Network) {
        synchronized(lock) {
            entries.remove(network)
        }
    }

    fun read(): List<NetworkSnapshotEntry> = synchronized(lock) { entries.values.toList() }
}

/** [NetworkSnapshot] 里的一条链路：能力 + 链路信息，由两个回调分别写入。 */
private data class NetworkSnapshotEntry(
    val capabilities: NetworkCapabilities?,
    val linkProperties: LinkProperties?
)
