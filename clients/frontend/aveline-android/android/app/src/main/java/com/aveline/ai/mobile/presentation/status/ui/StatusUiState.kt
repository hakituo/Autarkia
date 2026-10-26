package com.aveline.ai.mobile.presentation.status.ui

import com.aveline.ai.mobile.domain.models.Emotion
import com.aveline.ai.mobile.domain.models.LifeStatus
import kotlinx.serialization.json.JsonObject

/**
 * 状态面板 UI 状态
 *
 * 注意：这里**不包含时钟**。时钟每秒变一次，如果和别的字段放在同一个 StateFlow 里，
 * 每秒都会把整棵伴侣详情面板（以及常驻组合树里的聊天页）重新组合一遍，
 * 用户滑动详情页时就会掉帧。时钟单独走 [com.aveline.ai.mobile.presentation.status.StatusViewModel.clock]。
 *
 * @property lifeStatus 生命状态
 * @property emotion 当前情绪
 * @property emotionMix 情绪混合比例
 * @property connected WebSocket 连接状态
 * @property systemStats 系统统计
 * @property isLoading 是否加载中
 * @property isActionRunning 控制动作是否执行中
 * @property actionMessage 控制动作结果
 * @property error 错误信息
 */
data class StatusUiState(
    val lifeStatus: LifeStatus? = null,
    val emotion: Emotion = Emotion.NEUTRAL,
    val emotionMix: Map<String, Float> = emptyMap(),
    val connected: Boolean = false,
    val systemStats: JsonObject? = null,
    val isLoading: Boolean = false,
    val isActionRunning: Boolean = false,
    val actionMessage: String? = null,
    val error: String? = null
) {
    val hasLowStatus: Boolean
        get() = lifeStatus?.hasLowStatus() ?: false

    val lowestStatusValue: Float
        get() = lifeStatus?.getLowestStatus() ?: 0f

    val lowestStatusName: String
        get() {
            val status = lifeStatus ?: return ""
            val lowest = minOf(
                status.health to "健康",
                status.hunger to "饥饿",
                status.happiness to "快乐",
                status.energy to "能量"
            ) { a, b -> a.first.compareTo(b.first) }
            return lowest.second
        }

    val connectionStatusText: String
        get() = if (connected) "已连接" else "未连接"

    val healthPercent: Int
        get() = ((lifeStatus?.health ?: 0f) * 100).toInt()

    val hungerPercent: Int
        get() = ((lifeStatus?.hunger ?: 0f) * 100).toInt()

    val happinessPercent: Int
        get() = ((lifeStatus?.happiness ?: 0f) * 100).toInt()

    val energyPercent: Int
        get() = ((lifeStatus?.energy ?: 0f) * 100).toInt()
}
