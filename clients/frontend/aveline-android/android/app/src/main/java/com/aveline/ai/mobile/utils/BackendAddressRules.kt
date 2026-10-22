package com.aveline.ai.mobile.utils

/**
 * 后端地址的静态判定规则：把一个地址字符串归类成「局域网 / 组网 / 公网」，
 * 并回答「这个地址是否落在某个网段内」。
 *
 * 为什么要收敛成唯一实现：这套判据原先散在三处各写一份 —— `EndpointResolver` 的运行时
 * 物理兜底、`AppPreferences` 的槽位迁移、以及 `isLanOnlyHost` 的同类判断。任何一处改了
 * 判据，另外几处就会静默失效。最典型的是「Tailscale 的 `100.64.0.0/10` 段不算局域网」
 * 这条：漏掉一处，出门时就会把生效地址从组网强制切走，或让「组网优先于公网」的排序失效。
 *
 * 纯字符串函数，无 Android 依赖，可直接跑 JVM 单测（见 `BackendAddressRulesTest`）。
 */
internal object BackendAddressRules {

    /**
     * 取出 host 部分：去掉协议头、路径、端口，统一小写。空/非法地址返回空串。
     *
     * **先 lowercase 再去协议头**，顺序不能反：`removePrefix` 是大小写敏感的，
     * 反过来的话 `HTTPS://Host/x` 会在第一个 `/` 处截成 `HTTPS:`，最后得到 "https" 这种
     * 假 host —— 既不是私网也不是组网，被静默归成公网。
     */
    fun hostOf(raw: String): String = raw.trim()
        .lowercase()
        .removePrefix("https://")
        .removePrefix("http://")
        .substringBefore('/')
        .substringBefore(':')

    /**
     * 地址是否**只在局域网内才有意义**（私网 IPv4 / localhost / `.local`）。
     *
     * 用途是运行时的物理兜底：只要判定「私网地址 + 当前网络到不了它」，就可以断定这条链路
     * 物理上不通，不必再等探测结果。
     *
     * 域名（哪怕是内网 DNS）一律返回 false —— 它在蜂窝下也可能解析成功。
     */
    fun isLanOnlyHost(raw: String): Boolean {
        val host = hostOf(raw)
        if (host.isEmpty()) return false
        if (host == "localhost" || host.endsWith(".local")) return true
        return isPrivateIpv4(host)
    }

    /**
     * 地址是不是一个**私网 IPv4 字面量**（`10/8`、`172.16/12`、`192.168/16`）。
     *
     * 与 [isLanOnlyHost] 的区别只在域名：这里只认点分十进制字面量，`localhost` / `.local`
     * 一律 false。用途是「拿本机网段去判它有没有可能直达」—— 只有字面量才能做网段归属判断，
     * 域名得先解析，而裁决路径上不该做 DNS。
     *
     * 注意蜂窝数据的本机地址也常常是 `10.x` / `172.x`（运营商大内网），所以这个判据只回答
     * 「像不像内网地址」，**不能**单独回答「现在是不是在家」—— 后者要靠网段比对（见
     * [isHostCoveredBy]）或真实探测。
     */
    fun isPrivateIpv4(raw: String): Boolean {
        val octets = ipv4Octets(hostOf(raw)) ?: return false
        return octets[0] == 10 ||
            (octets[0] == 172 && octets[1] in 16..31) ||
            (octets[0] == 192 && octets[1] == 168)
    }

    /**
     * host 是否落在任一网段（CIDR）内。用于回答「本机当前这张网，和后端局域网地址
     * 是不是同一张网」—— 这比「有没有连 WiFi」可靠得多：在别人家的 WiFi 上也是 WiFi，
     * 但网段对不上，后端地址照样不可能直达。
     *
     * 约定：
     * - 只处理 IPv4；host 不是合法 IPv4 字面量（域名、IPv6）一律返回 false，
     *   调用方遇到 false 要回退到别的判据，不能直接当成「不可达」；
     * - `cidr` 支持 `"192.0.2.50/24"` 与裸 `"192.0.2.50"`（按 /32 处理）；
     * - **`/0`（默认路由）不参与判定**：它只说明包会被发出去，不说明能到；而且 VPN 常把
     *   默认路由拆成 `0.0.0.0/1` + `128.0.0.0/1`，一旦算进来，任何地址都会被判成「可达」，
     *   判据就失去意义了。所以调用方只应传**直连网段**（本机接口地址所属的网段）。
     */
    fun isHostCoveredBy(rawHost: String, cidrs: List<String>): Boolean {
        val host = ipv4ToInt(hostOf(rawHost)) ?: return false
        return cidrs.any { cidr ->
            val parsed = parseCidr(cidr) ?: return@any false
            parsed.prefixLength > 0 && (host and parsed.mask) == parsed.network
        }
    }

    /** 解析 `"a.b.c.d/len"`；非法（含前缀长度越界）返回 null。 */
    private fun parseCidr(raw: String): Cidr? {
        val trimmed = raw.trim()
        if (trimmed.isEmpty()) return null
        val address = ipv4ToInt(hostOf(trimmed)) ?: return null
        val lengthText = trimmed.substringAfter('/', "")
        val prefixLength = if (lengthText.isEmpty()) 32 else lengthText.toIntOrNull() ?: return null
        if (prefixLength !in 0..32) return null
        val mask = if (prefixLength == 0) 0 else -1 shl (32 - prefixLength)
        return Cidr(network = address and mask, prefixLength = prefixLength, mask = mask)
    }

    /** 一个已解析的网段：网络号 + 前缀长度 + 掩码。 */
    private data class Cidr(val network: Int, val prefixLength: Int, val mask: Int)

    /** 点分十进制转 32 位整数；非法返回 null。 */
    private fun ipv4ToInt(host: String): Int? {
        val octets = ipv4Octets(host) ?: return null
        return (octets[0] shl 24) or (octets[1] shl 16) or (octets[2] shl 8) or octets[3]
    }

    /**
     * 地址是否属于**点对点组网段**（Tailscale / WireGuard 常用的 CGNAT `100.64.0.0/10`）。
     *
     * 这一段必须与私网判据分开，两个方向的误判都有害：
     * - 判成私网 → 「蜂窝 + 私网地址就强制降级」的兜底会把组网地址一起切走；
     * - 判成公网 → 「出门时组网优先于公网域名」的排序失去依据，组网槽位永远排在公网后面。
     *
     * 它外观像内网但在蜂窝下可达，所以既不能进局域网候选，也不能当普通公网地址。
     */
    fun isVpnHost(raw: String): Boolean {
        val octets = ipv4Octets(hostOf(raw)) ?: return false
        return octets[0] == 100 && octets[1] in 64..127
    }

    /** 解析成四段 IPv4；不是合法点分十进制（含域名）返回 null。 */
    private fun ipv4Octets(host: String): List<Int>? {
        if (host.isEmpty()) return null
        val octets = host.split('.').map { it.toIntOrNull() ?: return null }
        if (octets.size != 4 || octets.any { it !in 0..255 }) return null
        return octets
    }
}
