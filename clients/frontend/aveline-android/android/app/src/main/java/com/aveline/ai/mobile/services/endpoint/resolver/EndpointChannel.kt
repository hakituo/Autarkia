package com.aveline.ai.mobile.services.endpoint.resolver

import com.aveline.ai.mobile.utils.BackendAddressRules

/**
 * 生效地址所属的通道，用于日志、设置页展示与候选排序。
 *
 * 从 [com.aveline.ai.mobile.services.endpoint.EndpointResolver] 的嵌套类型提出来，
 * 是因为候选排序判据（[ChannelPriority]）与网络监听（[NetworkWatcher]）都要用它，
 * 留在门面里会让子模块反向依赖门面，形成环。
 */
enum class EndpointChannel {
    /** 用户手动锁定的地址 */
    MANUAL,

    /** 局域网 */
    LAN,

    /** 组网通道（Tailscale 等点对点 VPN 的 100.x 地址） */
    VPN,

    /** 公网域名（Cloudflare Tunnel） */
    TUNNEL,

    /** 尚未裁决（进程刚起、槽位为空） */
    NONE
}

/**
 * 一次裁决的结果：生效地址 + 它属于哪条通道 + 这次裁决它到底通不通。
 *
 * [reachable] 是给界面用的诚实信号：所有候选都探不通时门面会**沿用**原地址
 * （不能把配置清成空），但那个地址此刻是连不上的，设置页不该继续把它显示成
 * 「当前通道：局域网」而让用户以为一切正常。默认 true 是为了兼容「还没裁决过」的初值。
 */
data class ResolvedEndpoint(
    val url: String,
    val channel: EndpointChannel,
    val reachable: Boolean = true
)

/**
 * 按**地址本身**判定通道，而不是按「它来自哪个槽位」。
 *
 * 为什么必须这样：槽位是可以被填错的 —— 局域网槽位里放一个公网域名（用户手填、
 * 导入设置、旧版本迁移都可能），或者放一个 Tailscale 的 `100.x`。若按槽位命名通道，
 * 设置页就会把「正在用公网域名」显示成「当前通道：局域网」，用户完全无法从界面上判断
 * 自己现在到底靠什么在连（这是实测踩到的坑：手动指定外部域名并连上之后，界面一直
 * 显示局域网）。
 *
 * 判据复用 [com.aveline.ai.mobile.utils.BackendAddressRules]（与运行时兜底同一份）：
 * 私网 / localhost / `.local` → [EndpointChannel.LAN]；CGNAT 组网段 → [EndpointChannel.VPN]；
 * 其余（公网域名、公网 IP）→ [EndpointChannel.TUNNEL]。用户手动锁定的地址单独归为
 * [EndpointChannel.MANUAL]（它的语义是「不再自动切换」，与地址类型无关）。
 */
internal fun channelOf(url: String, manualLocked: Boolean): EndpointChannel = when {
    url.isBlank() -> EndpointChannel.NONE
    manualLocked -> EndpointChannel.MANUAL
    BackendAddressRules.isLanOnlyHost(url) -> EndpointChannel.LAN
    BackendAddressRules.isVpnHost(url) -> EndpointChannel.VPN
    else -> EndpointChannel.TUNNEL
}
