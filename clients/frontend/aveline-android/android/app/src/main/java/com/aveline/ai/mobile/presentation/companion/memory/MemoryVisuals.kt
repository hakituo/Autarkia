package com.aveline.ai.mobile.presentation.companion.memory

import androidx.compose.ui.graphics.Color
import com.aveline.ai.mobile.presentation.theme.Sand
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * 「重要」统一用沙金色。
 *
 * 原来是 #FFC107 琥珀——那是 Material 警示色的黄，在深色底上非常抢眼，
 * 一屏里出现五六个星标就把正文彻底压下去了。沙金与强调色同一明度带，够醒目但不刺眼。
 */
internal val MemoryImportantColor = Sand

/** 树状引导线 / 行分隔线：8% 白 */
internal val MemoryTreeLineColor = Color(0x26FFFFFF)

/**
 * 话题颜色。
 *
 * 14 种高饱和话题色（#F472B6 / #FB7185 / #38BDF8 …）换成 8 种低彩度色：
 * 图上分得清，但整体不会像撒了一把糖果。同一家族（健康与工作、娱乐与节日、
 * 技术与财务、个人与偏好）共用一色，减少需要辨认的色相数量。
 */
internal fun memoryTopicColor(key: String): Color = when (key) {
    "learning" -> Color(0xFFA9A3CC)
    "daily" -> Color(0xFF9DB4C4)
    "emotion", "sensitive" -> Color(0xFFC8A19C)
    "relationship" -> Color(0xFFC4A2B6)
    "health", "work" -> Color(0xFFA2C0A6)
    "entertainment", "festival" -> Color(0xFFCBB88E)
    "tech", "finance" -> Color(0xFF93BAB3)
    else -> Color(0xFFB0B8C0)
}

private val TIMESTAMP_FORMATTER: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")

/** 绝对时间，详情面板用 */
internal fun formatMemoryTimestamp(instant: Instant): String =
    instant.atZone(ZoneId.systemDefault()).format(TIMESTAMP_FORMATTER)

/** 只取时分：记忆树条目旁边空间紧，日期已经由时间桶表达了 */
private val CLOCK_FORMATTER: DateTimeFormatter = DateTimeFormatter.ofPattern("HH:mm")

internal fun formatMemoryClock(instant: Instant): String =
    instant.atZone(ZoneId.systemDefault()).format(CLOCK_FORMATTER)
