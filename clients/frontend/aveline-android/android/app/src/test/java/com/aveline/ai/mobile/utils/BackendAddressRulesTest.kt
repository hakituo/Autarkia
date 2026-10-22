package com.aveline.ai.mobile.utils

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * BackendAddressRules 的回归测试：地址分类是「通道裁决」与「槽位迁移」共用的判据。
 *
 * 三类地址必须互不混淆，判错方向的代价各不相同：
 * - 组网地址（CGNAT `100.64.0.0/10`）误判成私网 → 蜂窝下「私网地址就强制降级」的兜底
 *   会把生效地址从组网切走；误判成公网 → 「出门时组网优先于公网」的排序失去依据；
 * - 私网地址漏判 → 回到「开了流量切不过去」的老问题；
 * - 公网域名误判成私网 → 在家 WiFi 下被强行切走，属严重误伤。
 */
class BackendAddressRulesTest {

    @Test
    fun `Tailscale 组网段判定为组网地址`() {
        // 100.64.0.0/10 的完整边界：100.64.0.0 ~ 100.127.255.255
        listOf(
            "http://100.64.0.1:8000",
            "http://100.64.0.1:8000",
            "http://100.127.255.254:8000",
            "http://100.64.0.0:8000",
            "https://100.127.255.255",
            "100.64.0.1:8000",
            "http://100.64.0.1:8000/api/v1"
        ).forEach { url ->
            assertTrue("$url 应被判定为组网地址", BackendAddressRules.isVpnHost(url))
        }
    }

    @Test
    fun `组网段之外的 100 段地址不判定为组网`() {
        // 100.64.0.0/10 之外仍属公网，判成组网会让槽位迁移把公网地址塞进组网槽位
        listOf(
            "http://100.63.255.255:8000",
            "http://100.128.0.0:8000",
            "http://100.0.0.1:8000",
            "http://100.255.255.255:8000"
        ).forEach { url ->
            assertFalse("$url 不属于 CGNAT 组网段，不应判定为组网地址", BackendAddressRules.isVpnHost(url))
        }
    }

    @Test
    fun `私网与公网地址都不判定为组网`() {
        listOf(
            "http://192.0.2.1:8000",
            "http://10.0.0.5:8000",
            "https://ai.example.com",
            "http://8.8.8.8:8000",
            "http://localhost:8000"
        ).forEach { url ->
            assertFalse("$url 不应判定为组网地址", BackendAddressRules.isVpnHost(url))
        }
    }

    @Test
    fun `组网地址与局域网专用地址互斥`() {
        // 两条判据各自对应一条兜底分支，同时为真会让「蜂窝 + 私网 → 强制降级」
        // 把组网地址也一起切走，这是新通道最容易踩的坑
        val vpn = "http://100.64.0.1:8000"
        assertTrue(BackendAddressRules.isVpnHost(vpn))
        assertFalse(BackendAddressRules.isLanOnlyHost(vpn))
    }

    @Test
    fun `局域网专用判据与运行时兜底保持一致`() {
        listOf(
            "http://192.0.2.1:8000",
            "http://10.0.0.5:8000",
            "http://172.16.0.1:8000",
            "http://172.31.255.254:8000",
            "http://localhost:8000",
            "http://xiaoyou.local:8000",
            "192.0.2.1:8000",
            "http://192.0.2.1:8000/api/v1"
        ).forEach { url ->
            assertTrue("$url 应被判定为局域网专用地址", BackendAddressRules.isLanOnlyHost(url))
        }
        listOf(
            "https://ai.example.com",
            "https://xxx.trycloudflare.com",
            "http://8.8.8.8:8000",
            "http://114.114.114.114",
            "http://172.15.0.1:8000",
            "http://172.32.0.1:8000",
            "http://192.169.1.1:8000",
            "http://11.0.0.1:8000",
            "http://192.0.2.256:8000",
            "http://192.168.31:8000",
            "tunnel.example.com/api/v1"
        ).forEach { url ->
            assertFalse("$url 不应被判定为局域网专用地址", BackendAddressRules.isLanOnlyHost(url))
        }
    }

    @Test
    fun `空地址与非法地址对两条判据都安全返回 false`() {
        listOf("", "   ", "http://", "not a url").forEach { url ->
            assertFalse("空/非法地址不应判定为局域网专用: '$url'", BackendAddressRules.isLanOnlyHost(url))
            assertFalse("空/非法地址不应判定为组网地址: '$url'", BackendAddressRules.isVpnHost(url))
        }
    }

    @Test
    fun `hostOf 去掉协议头 路径 端口并统一小写`() {
        assertEquals("ai.example.com", BackendAddressRules.hostOf("HTTPS://Ai.Example.COM:443/api/v1"))
        assertEquals("192.0.2.1", BackendAddressRules.hostOf("  http://192.0.2.1:8000/api/v1  "))
        assertEquals("", BackendAddressRules.hostOf(""))
    }

    @Test
    fun `私网字面量判据只认 IPv4 不认域名`() {
        // 这条判据决定「要不要拿本机网段去比对」，域名得先解析，裁决路径上不做 DNS，
        // 所以必须返回 false 让调用方回退到别的判据（否则会把内网域名判成不可达）
        listOf(
            "http://192.0.2.1:8000",
            "http://10.0.0.5:8000",
            "http://172.16.0.1:8000",
            "http://172.31.255.254:8000",
            "192.0.2.1:8000",
            "http://192.0.2.1:8000/api/v1"
        ).forEach { url ->
            assertTrue("$url 是私网字面量", BackendAddressRules.isPrivateIpv4(url))
        }
        listOf(
            "http://localhost:8000",
            "http://xiaoyou.local:8000",
            "https://ai.example.com",
            "http://100.64.0.1:8000",
            "http://8.8.8.8:8000",
            "http://172.15.0.1:8000",
            "http://172.32.0.1:8000",
            "http://192.168.31:8000"
        ).forEach { url ->
            assertFalse("$url 不是私网字面量", BackendAddressRules.isPrivateIpv4(url))
        }
    }

    @Test
    fun `网段归属判据按前缀长度匹配`() {
        // 在家：本机 192.0.2.50/24，后端 192.0.2.1 → 同一张网
        assertTrue(BackendAddressRules.isHostCoveredBy("192.0.2.1", listOf("192.0.2.50/24")))
        // 在别人家的 WiFi：本机 192.168.1.50/24，后端还是家里那个地址 → 不在同一张网
        assertFalse(BackendAddressRules.isHostCoveredBy("192.0.2.1", listOf("192.168.1.50/24")))
        // 大前缀（部分路由器/运营商给 /16）也要能覆盖
        assertTrue(BackendAddressRules.isHostCoveredBy("192.0.2.1", listOf("192.0.2.50/16")))
        // 多张网卡时任意一条命中即可（家里 WiFi + 蜂窝 + 组网同时存在）
        assertTrue(
            BackendAddressRules.isHostCoveredBy(
                "10.0.0.5",
                listOf("192.0.2.50/24", "100.64.0.1/32", "10.0.0.7/8")
            )
        )
        // 裸地址按 /32 处理
        assertTrue(BackendAddressRules.isHostCoveredBy("192.0.2.1", listOf("192.0.2.1")))
        assertFalse(BackendAddressRules.isHostCoveredBy("192.0.2.1", listOf("192.0.2.226")))
    }

    @Test
    fun `默认路由不参与网段归属判定`() {
        // 关键回归：VPN 常把默认路由拆成 0.0.0.0/1 + 128.0.0.0/1，
        // 一旦算进来，任意地址都会被判成「可达」，这条判据就废了
        assertFalse(BackendAddressRules.isHostCoveredBy("192.0.2.1", listOf("0.0.0.0/0")))
        assertFalse(BackendAddressRules.isHostCoveredBy("192.0.2.1", listOf("0.0.0.0/1")))
        assertFalse(BackendAddressRules.isHostCoveredBy("192.0.2.1", listOf("128.0.0.0/1")))
    }

    @Test
    fun `网段归属判据对域名与非法输入返回 false`() {
        // 调用方遇到 false 必须回退到别的判据，不能直接当成「不可达」
        listOf("", "   ", "not a url", "http://xiaoyou.local:8000", "http://100.64.0.1:8000").forEach { host ->
            assertFalse(
                "非 IPv4 字面量 '$host' 不应判定为落在网段内",
                BackendAddressRules.isHostCoveredBy(host, listOf("192.0.2.50/24"))
            )
        }
        // 非法的 CIDR 条目只跳过自己，不影响其他条目
        assertTrue(
            BackendAddressRules.isHostCoveredBy(
                "192.0.2.1",
                listOf("192.0.2.50/33", "192.0.2.50/-1", "abc", "192.0.2.50/24")
            )
        )
    }
}
