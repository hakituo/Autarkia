package com.aveline.ai.mobile.services.endpoint.resolver

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [ChannelPriority] 的回归测试：它决定「后台周期定时器要不要真的发探测请求」。
 *
 * 判错方向的代价不对称：
 * - 该探却判 false → 通道卡在低优先级候选上（用户体感「开着组网却一直走公网」，
 *   或者「在别处连了 WiFi，却一直卡在家里的内网地址上连不上」）；
 * - 不该探却判 true → 每 5 分钟白跑一轮探测（局域网候选必然超时，白耗电）。
 *
 * 所以每一档都要把「已经是最优」和「还有更优」两侧钉住。
 *
 * `lanPossible` 的语义是「局域网候选在当前网络下有没有可能直达」（本机网段是否覆盖它），
 * **不是**「有没有连 WiFi」—— 相关场景在下面的用例里逐条钉住。
 */
class ChannelPriorityTest {

    private fun hasBetter(
        current: EndpointChannel,
        lanPossible: Boolean,
        lanUrl: String = "",
        vpnUrl: String = "",
        tunnelUrl: String = ""
    ) = ChannelPriority.hasBetterCandidate(current, lanPossible, lanUrl, vpnUrl, tunnelUrl)

    @Test
    fun `手动锁定永不重选`() {
        // 用户明确指定的地址不该被后台任务悄悄改掉，槽位再全也不探
        assertFalse(hasBetter(EndpointChannel.MANUAL, true, "http://192.168.1.5:8000", "http://100.64.0.1:8000", "https://a.example.com"))
        assertFalse(hasBetter(EndpointChannel.MANUAL, false, "http://192.168.1.5:8000", "http://100.64.0.1:8000", "https://a.example.com"))
    }

    @Test
    fun `局域网是最高优先级 还在本机网段内就不重选`() {
        assertFalse(hasBetter(EndpointChannel.LAN, lanPossible = true, vpnUrl = "http://100.64.0.1:8000", tunnelUrl = "https://a.example.com"))
    }

    @Test
    fun `局域网候选已不可达 应重选`() {
        // 出门（蜂窝）与「在别人家连了 WiFi」都落在这里：网段对不上，私网地址必然不通，
        // 只要配了远程通道就值得重选
        assertTrue(hasBetter(EndpointChannel.LAN, lanPossible = false, vpnUrl = "http://100.64.0.1:8000"))
        assertTrue(hasBetter(EndpointChannel.LAN, lanPossible = false, tunnelUrl = "https://a.example.com"))
    }

    @Test
    fun `局域网候选已不可达且没有任何远程通道 不必重选`() {
        assertFalse(hasBetter(EndpointChannel.LAN, lanPossible = false))
    }

    @Test
    fun `组网只在回家后才值得重选`() {
        // 局域网是唯一比组网更优的候选，且只有它真的在本机网段内时才可能探通
        assertTrue(hasBetter(EndpointChannel.VPN, lanPossible = true, lanUrl = "http://192.168.1.5:8000"))
        assertFalse(hasBetter(EndpointChannel.VPN, lanPossible = true))
        assertFalse(hasBetter(EndpointChannel.VPN, lanPossible = false, lanUrl = "http://192.168.1.5:8000"))
    }

    @Test
    fun `公网是最低优先级 上面任何一条可用都该升上去`() {
        assertTrue(hasBetter(EndpointChannel.TUNNEL, lanPossible = true, lanUrl = "http://192.168.1.5:8000"))
        assertTrue(hasBetter(EndpointChannel.TUNNEL, lanPossible = false, vpnUrl = "http://100.64.0.1:8000"))
    }

    @Test
    fun `公网且没有更优候选时不重选`() {
        // 蜂窝 + 组网槽位空 = 已经在唯一可用通道上，再探也是白跑
        assertFalse(hasBetter(EndpointChannel.TUNNEL, lanPossible = false))
        assertFalse(hasBetter(EndpointChannel.TUNNEL, lanPossible = true))
    }

    @Test
    fun `尚未裁决时总要探一次`() {
        assertTrue(hasBetter(EndpointChannel.NONE, lanPossible = false))
        assertTrue(hasBetter(EndpointChannel.NONE, lanPossible = true))
    }

    @Test
    fun `在别人家的 WiFi 上 局域网通道不该被当成已是最优`() {
        // 关键回归：这里链路类型是 wifi，但本机网段和后端地址不在同一张网里，
        // 所以 lanPossible=false。旧判据用「有没有 WiFi」会判 false（= 不必重选），
        // 于是用户就卡在一个永远连不上的内网地址上，只能手动改地址。
        assertTrue(hasBetter(EndpointChannel.LAN, lanPossible = false, tunnelUrl = "https://a.example.com"))
    }
}
