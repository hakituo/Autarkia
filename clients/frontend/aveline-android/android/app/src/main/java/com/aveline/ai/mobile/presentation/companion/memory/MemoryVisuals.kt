package com.aveline.ai.mobile.presentation.companion.memory

import androidx.compose.ui.graphics.Color
import com.aveline.ai.mobile.domain.models.MemoryType
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** 重要性 / 强调统一的琥珀色，与旧版星标保持一致 */
internal val MemoryImportantColor = Color(0xFFFFC107)

/** 树状引导线颜色 */
internal val MemoryTreeLineColor = Color(0x26FFFFFF)

/** 记忆类型对应颜色（与后端 taxonomy 分类对齐） */
internal fun memoryTypeColor(type: MemoryType): Color = when (type) {
    MemoryType.DAILY -> Color(0xFF2196F3)
    MemoryType.LEARNING -> Color(0xFF9C27B0)
    MemoryType.WORK -> Color(0xFF4CAF50)
    MemoryType.FESTIVAL -> Color(0xFFFF9800)
    MemoryType.HEALTH -> Color(0xFFF44336)
    MemoryType.PROFILE -> Color(0xFF00BCD4)
    MemoryType.ENTERTAINMENT -> Color(0xFFE91E63)
    MemoryType.FINANCE -> Color(0xFF3F51B5)
    MemoryType.TECH -> Color(0xFF009688)
    MemoryType.EMOTION -> Color(0xFFFF5722)
    MemoryType.RELATIONSHIP -> Color(0xFF795548)
    MemoryType.SENSITIVE -> Color(0xFFC62828)
    MemoryType.PREFERENCE -> Color(0xFF9C27B0)
    MemoryType.THINKING -> Color(0xFF607D8B)
    MemoryType.UNCATEGORIZED,
    MemoryType.UNKNOWN -> Color(0xFF9E9E9E)
}

/**
 * 话题颜色。
 *
 * 用低饱和的深色主题友好色板；未登记的话题统一走中性灰，不随机取色，
 * 保证同一话题在概览 chips 和树节点上颜色一致。
 */
internal fun memoryTopicColor(key: String): Color = when (key) {
    "relationship" -> Color(0xFFF472B6)
    "emotion" -> Color(0xFFFB7185)
    "daily" -> Color(0xFF38BDF8)
    "learning" -> Color(0xFFA78BFA)
    "work" -> Color(0xFF34D399)
    "health" -> Color(0xFF4ADE80)
    "profile" -> Color(0xFF22D3EE)
    "preference" -> Color(0xFFC084FC)
    "tech" -> Color(0xFF2DD4BF)
    "entertainment" -> Color(0xFFFBBF24)
    "finance" -> Color(0xFF818CF8)
    "festival" -> Color(0xFFFB923C)
    "sensitive" -> Color(0xFFF87171)
    "thinking" -> Color(0xFF94A3B8)
    else -> Color(0xFF94A3B8)
}

private val TIMESTAMP_FORMATTER: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")

/** 绝对时间，详情弹窗用 */
internal fun formatMemoryTimestamp(instant: Instant): String =
    instant.atZone(ZoneId.systemDefault()).format(TIMESTAMP_FORMATTER)
