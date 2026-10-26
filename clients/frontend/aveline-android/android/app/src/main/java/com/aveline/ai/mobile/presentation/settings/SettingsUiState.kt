package com.aveline.ai.mobile.presentation.settings

import com.aveline.ai.mobile.services.endpoint.resolver.EndpointCandidateProbe

/**
 * 设置界面 UI 状态。
 *
 * 设置页已从五个 Tab 收成一页分组列表：这里只保留列表需要的开关、地址槽位、
 * 当前通道与版本信息；模型 / 回复长度 / 语音等已从设置页移除。
 */
data class SettingsUiState(
    // 权限（无障碍与 Shizuku 由界面层检测，避免 ViewModel 依赖系统服务）
    val hasUsageStatsPermission: Boolean = false,
    val hasNotificationPermission: Boolean = false,

    // 隐私 / 同步
    val isContextSyncEnabled: Boolean = true,
    val residentModeEnabled: Boolean = false,
    /** 开启常驻模式时，若不在电池优化白名单则置 true，UI 弹引导对话框 */
    val showBatteryOptimizationRequest: Boolean = false,

    // 地址槽位
    /** 手动锁定的后端地址；留空 = 自动在局域网 / 组网 / 公网之间选择 */
    val backendUrl: String = "",
    /** 局域网地址槽位（自动发现或手填），在家优先走它 */
    val lanUrl: String = "",
    /** 组网通道槽位（Tailscale 点对点地址），外出时优先于公网域名 */
    val vpnUrl: String = "",
    /** 公网域名槽位（Cloudflare Tunnel），组网不通时的兜底 */
    val tunnelUrl: String = "",
    /** 当前生效地址（裁决结果），只读展示 */
    val activeUrl: String = "",
    /** 当前生效通道的中文名（局域网 / 组网 / 公网 / 手动锁定 / 未确定） */
    val activeChannel: String = "",
    /**
     * 当前生效地址这次裁决到底通不通。
     *
     * 全都不通时裁决器会沿用原地址（不把配置清成空），此时界面必须显示「不可达」，
     * 否则用户看到的还是「当前通道：局域网」，会以为问题在别处。
     */
    val activeReachable: Boolean = true,
    /** 当前生效地址最近一次探测延迟；没探过或不可达时为 null */
    val activeLatencyMs: Long? = null,
    val accessToken: String = "",
    val isTestingConnection: Boolean = false,
    /** 重新裁决 / 保存地址后的重探中，与「测试连接」分开，两个按钮各自显示 loading。 */
    val isReprobing: Boolean = false,
    val connectionTestResult: ConnectionTestResult? = null,

    // 网络页候选探测
    val candidateProbes: List<EndpointCandidateProbe> = emptyList(),
    val isProbingCandidates: Boolean = false,

    // 对话
    val autoTtsEnabled: Boolean = false,
    /** 括号里的动作 / 场景描写是否渲染成居中旁白 */
    val stageDirectionEnabled: Boolean = true,

    // 数据 / 版本
    val appVersion: String = "1.0.0",
    val buildVersion: String = "1",
    val showClearConfirm: Boolean = false,
    val isClearing: Boolean = false,
    /** 清除历史失败时的错误信息，非 null 表示需向用户展示 */
    val clearError: String? = null
) {
    /** 状态卡上的地址：去掉协议头，长域名交给 maxLines 截断。 */
    val activeAddress: String
        get() = addressWithoutScheme(activeUrl)
}

/** 连接测试结果 */
data class ConnectionTestResult(
    val success: Boolean,
    val message: String
)

private val BACKEND_URL_PATTERN = Regex("^(https?://).+")

/**
 * 地址槽位是否「填了但格式不对」，供输入框标红与保存按钮禁用。
 *
 * 留空合法：局域网 / 组网 / 公网 / 手动锁定都允许为空（空 = 该通道未启用）。
 */
internal fun isInvalidBackendUrl(value: String): Boolean {
    val trimmed = value.trim()
    return trimmed.isNotEmpty() && !BACKEND_URL_PATTERN.matches(trimmed)
}
