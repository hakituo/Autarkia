package com.aveline.ai.mobile.services.endpoint.resolver

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * [channelOf] 的回归测试：它决定设置页「当前通道」显示什么。
 *
 * 这条判据是按**地址本身**判的，不是按「来自哪个槽位」—— 槽位可以被填错（局域网槽位里放
 * 公网域名、放 Tailscale 的 `100.x`），照槽位命名就会把「正在走公网域名」显示成
 * 「当前通道：局域网」。实测用户就是这么被误导的：手动指定外部域名并连上之后，
 * 界面一直显示局域网，完全无法从界面上判断自己靠什么在连。
 */
class EndpointChannelTest {

    @Test
    fun `空地址归为未裁决`() {
        // 四个槽位全空（纯自动发现模式）= 还没裁决过，界面显示「未确定」
        assertEquals(EndpointChannel.NONE, channelOf("", manualLocked = false))
        assertEquals(EndpointChannel.NONE, channelOf("   ", manualLocked = false))
        assertEquals(EndpointChannel.NONE, channelOf("", manualLocked = true))
    }

    @Test
    fun `手动锁定与地址类型无关`() {
        // 手动锁定的语义是「不再自动切换」，所以填什么地址都显示「手动锁定」
        listOf(
            "https://ai.example.com",
            "http://192.0.2.1:8000",
            "http://100.64.0.1:8000"
        ).forEach { url ->
            assertEquals("$url 手动锁定时应归为 MANUAL", EndpointChannel.MANUAL, channelOf(url, manualLocked = true))
        }
    }

    @Test
    fun `私网地址归为局域网`() {
        listOf(
            "http://192.0.2.1:8000",
            "http://10.0.0.5:8000",
            "http://172.16.0.1:8000",
            "http://localhost:8000",
            "http://xiaoyou.local:8000"
        ).forEach { url ->
            assertEquals("$url 应归为局域网", EndpointChannel.LAN, channelOf(url, manualLocked = false))
        }
    }

    @Test
    fun `组网段归为组网`() {
        listOf(
            "http://100.64.0.1:8000",
            "http://100.64.0.1:8000",
            "http://100.127.255.254:8000"
        ).forEach { url ->
            assertEquals("$url 应归为组网", EndpointChannel.VPN, channelOf(url, manualLocked = false))
        }
    }

    @Test
    fun `公网域名与公网 IP 归为公网`() {
        listOf(
            "https://ai.example.com",
            "https://xxx.trycloudflare.com",
            "http://8.8.8.8:8000",
            "http://100.128.0.0:8000"
        ).forEach { url ->
            assertEquals("$url 应归为公网", EndpointChannel.TUNNEL, channelOf(url, manualLocked = false))
        }
    }

    @Test
    fun `槽位填错时按地址本身归通道 不按槽位名`() {
        // 关键回归：局域网槽位里放了公网域名（手填 / 导入设置 / 旧版本迁移都可能），
        // 显示成「局域网」会让用户以为「在家才连得上」，实际它在外网也能用
        assertEquals(EndpointChannel.TUNNEL, channelOf("https://ai.example.com", manualLocked = false))
        // 局域网槽位里放了 Tailscale 地址：它需要手机开着组网，显示「局域网」同样会误导
        assertEquals(EndpointChannel.VPN, channelOf("http://100.64.0.1:8000", manualLocked = false))
        // 反过来：公网槽位里放了私网地址，就该显示局域网（地址才是事实）
        assertEquals(EndpointChannel.LAN, channelOf("http://192.0.2.1:8000", manualLocked = false))
    }
}
