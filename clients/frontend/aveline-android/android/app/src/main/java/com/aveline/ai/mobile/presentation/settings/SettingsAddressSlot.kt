package com.aveline.ai.mobile.presentation.settings

import com.aveline.ai.mobile.services.endpoint.resolver.EndpointChannel

/**
 * 设置页可编辑的地址槽位。
 *
 * 顺序就是裁决顺序：局域网 → 组网 → 公网域名；[MANUAL] 不在候选链里，
 * 非空时直接压过所有自动候选。
 */
internal enum class SettingsAddressSlot(
    val title: String,
    val sheetTitle: String,
    val kicker: String,
    val hint: String,
    val placeholder: String,
    val number: Int?,
    val channel: EndpointChannel?
) {
    LAN(
        title = "局域网",
        sheetTitle = "局域网地址",
        kicker = "候选地址 1",
        hint = "在家优先。同一个 WiFi 下自动走它；留空则等待启动时的自动发现。",
        placeholder = "http://192.0.2.10:8000",
        number = 1,
        channel = EndpointChannel.LAN
    ),
    VPN(
        title = "组网",
        sheetTitle = "组网地址",
        kicker = "候选地址 2",
        hint = "Tailscale 等点对点地址，手机需要开着组网。连不上时会退回公网域名。",
        placeholder = "http://100.x.y.z:8000",
        number = 2,
        channel = EndpointChannel.VPN
    ),
    TUNNEL(
        title = "公网域名",
        sheetTitle = "公网域名",
        kicker = "候选地址 3",
        hint = "组网不通时的兜底，需要 Cloudflare Tunnel 已启动。",
        placeholder = "https://your-domain.example.com",
        number = 3,
        channel = EndpointChannel.TUNNEL
    ),
    MANUAL(
        title = "手动锁定",
        sheetTitle = "手动锁定",
        kicker = "其他",
        hint = "填写后不再自动切换通道；留空恢复自动选择。",
        placeholder = "留空 = 自动选择",
        number = null,
        channel = null
    )
}

/** 去掉协议头，给状态卡与候选行做紧凑展示。 */
internal fun addressWithoutScheme(url: String): String =
    url.trim().removePrefix("https://").removePrefix("http://").trimEnd('/')

/**
 * 比较两个地址是否指向同一入口。
 *
 * 用户可能填 `192.0.2.1:8000`，探测结果会归一化成 `http://192.0.2.1:8000`，
 * 逐字符比较会让延迟永远匹配不上。
 */
internal fun sameAddress(left: String, right: String): Boolean {
    if (left.isBlank() || right.isBlank()) return false
    return addressWithoutScheme(left).equals(addressWithoutScheme(right), ignoreCase = true)
}

/** 令牌只显示末四位，空值显示「未设置」。 */
internal fun maskedToken(token: String): String {
    val trimmed = token.trim()
    if (trimmed.isEmpty()) return "未设置"
    val tail = trimmed.takeLast(4)
    return "••••••$tail"
}
