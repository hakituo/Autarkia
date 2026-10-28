package com.aveline.ai.mobile.presentation.study.today

import com.aveline.ai.mobile.domain.models.PlanItem
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.roundToInt

/**
 * 「今天」页的纯文案口径。
 *
 * 这些函数不依赖 Composable，便于单测；UI 只负责排版，
 * 避免时区 / 补零 / 已学分钟这类细节散落在各个 @Composable 里。
 */

/** 页头日期：`10月25日 周日`；解析失败时原样返回。 */
internal fun formatTodayDateLabel(date: String): String {
    if (date.isBlank()) return ""
    return runCatching {
        val source = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
        val target = SimpleDateFormat("M月d日 EEE", Locale.CHINA)
        target.format(source.parse(date) ?: Date())
    }.getOrDefault(date)
}

/** 首帧还没拿到 DailyPlan 时，页头回落成本机今天。 */
internal fun currentTodayDateLabel(): String {
    val today = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())
    return formatTodayDateLabel(today)
}

/**
 * 计划总时长的紧凑写法：`4h 05min`。
 *
 * 与 [com.aveline.ai.mobile.presentation.study.formatStudyMinutes] 的区别只在
 * 分钟补零 —— 设计稿里「计划共 4h 05min」需要两位数分钟，避免和小时位挤在一起。
 */
internal fun formatPlanSpan(minutes: Int): String {
    val safe = minutes.coerceAtLeast(0)
    val hours = safe / 60
    val rest = safe % 60
    return when {
        hours <= 0 -> "${rest}min"
        rest == 0 -> "${hours}h"
        rest < 10 -> "${hours}h 0${rest}min"
        else -> "${hours}h ${rest}min"
    }
}

/** 任务行的时长：只报预计时长，实际用时只出现在「下一项」里。 */
internal fun taskDurationText(item: PlanItem): String =
    "${item.estimatedDurationMinutes.coerceAtLeast(0)} 分钟"

/** 「下一项」的补充行；进行中带上已学分钟：`14:00 · 已学 18 / 45 分钟`。 */
internal fun nextTaskDetail(item: PlanItem): String {
    val time = item.time.ifBlank { "灵活" }
    val estimate = item.estimatedDurationMinutes.coerceAtLeast(0)
    val actual = item.actualMinutes.takeIf { it >= 1.0 }?.roundToInt()
    return if (actual != null && estimate > 0) {
        "$time · 已学 $actual / $estimate 分钟"
    } else {
        "$time · $estimate 分钟"
    }
}

/** 只有高优先才在行里额外标出；普通优先级不占版面。 */
internal fun isHighPriority(item: PlanItem): Boolean =
    item.priority == "high" || item.priority == "urgent"

internal fun priorityLabel(priority: String): String = when (priority) {
    "urgent" -> "紧急"
    "high" -> "高优先"
    "low" -> "低优先"
    else -> ""
}
