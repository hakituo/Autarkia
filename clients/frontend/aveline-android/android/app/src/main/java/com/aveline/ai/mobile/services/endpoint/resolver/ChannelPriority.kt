package com.aveline.ai.mobile.services.endpoint.resolver

/**
 * 候选通道的排序判据。
 *
 * 纯函数、无 Android 依赖，可直接跑 JVM 单测 —— 这些判据原本藏在门面的私有方法里，
 * 只能靠真机验证，而它们决定的是「后台定时器要不要发探测请求」这种耗电行为。
 *
 * 候选优先级（见 `EndpointResolver.resolve()`）：
 * 手动锁定 > 局域网（仅当它在当前网段内）> 组网 > 公网域名。
 */
internal object ChannelPriority {

    /**
     * 当前通道之外，还有没有「更优、且在当前网络下有可能可用」的候选。
     *
     * 只做省电的前置判断，不改变裁决顺序：判 true 时仍走完整探测，探不通就保持原通道。
     * 判 false 的三种情况 —— 手动锁定（用户指定的地址不该被后台改掉）、
     * 局域网且它确实在本机网段内（它已是最高优先级）、组网且没回家（组网已是当前最优的
     * 远程通道）。
     *
     * @param lanPossible 局域网候选在当前网络下有没有可能直达。**不是**「有没有连 WiFi」：
     *   在别人家的 WiFi 上也是 WiFi，但家里的内网地址在那张网里根本不存在，
     *   此时它既不该被当成「已是最优」，也不该拦住「回家后升回局域网」的判断 ——
     *   两种情况都恰好由「网段是否覆盖」这一条回答。
     */
    fun hasBetterCandidate(
        current: EndpointChannel,
        lanPossible: Boolean,
        lanUrl: String,
        vpnUrl: String,
        tunnelUrl: String
    ): Boolean = when (current) {
        // 用户强制指定的地址不该被后台任务悄悄改掉
        EndpointChannel.MANUAL -> false
        // 局域网是最高优先级：还在本机网段内就没必要探；网段对不上（出门 / 换了别的 WiFi）
        // 才值得重选 —— 少了这一条，用户会卡在一个连不上的内网地址上等下一次连接失败
        EndpointChannel.LAN -> !lanPossible && (vpnUrl.isNotEmpty() || tunnelUrl.isNotEmpty())
        // 组网已是最优远程通道，唯一值得试的是「回家后切回局域网」
        EndpointChannel.VPN -> lanPossible && lanUrl.isNotEmpty()
        // 公网是最低优先级：上面任何一条可用都该升上去
        EndpointChannel.TUNNEL -> (lanPossible && lanUrl.isNotEmpty()) || vpnUrl.isNotEmpty()
        // 进程刚起、还没裁决过，值得探一次
        EndpointChannel.NONE -> true
    }
}
