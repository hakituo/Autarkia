package com.aveline.ai.mobile.presentation.study

import com.aveline.ai.mobile.domain.models.PlanItem
import kotlin.math.roundToInt

/**
 * 计划项的实际用时文案。
 *
 * 词汇任务由背单词前台计时回填 `actual_minutes`，此时计划卡要显示真实用时
 * 而不是预估；不足1分钟（或后端没给）时返回 null，由调用方回退到预计时长。
 *
 * 注意：今日进度条、`totalPlannedMinutes()` 等聚合口径仍按预计时长算，
 * 不要改用这个函数。
 */
internal fun planItemActualText(item: PlanItem): String? =
    item.actualMinutes.takeIf { it >= 1.0 }?.let { "实际 ${it.roundToInt()} 分钟" }
