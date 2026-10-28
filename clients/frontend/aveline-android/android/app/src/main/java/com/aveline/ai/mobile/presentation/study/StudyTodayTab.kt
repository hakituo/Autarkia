package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.PlanItem
import com.aveline.ai.mobile.presentation.study.today.PlanItemDetailSheet
import com.aveline.ai.mobile.presentation.study.today.TodayNextTask
import com.aveline.ai.mobile.presentation.study.today.TodayProgress
import com.aveline.ai.mobile.presentation.study.today.TodayTaskRow
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * Study 的执行首页（今天）。
 *
 * 页面只有一个主动作：「下一项」上的实心按钮。其余信息按重要性降级：
 * 进度（大数字 + 细条）→ 下一项 → 任务行 → 底部任务详情面板。
 * 具体排版在同包 [com.aveline.ai.mobile.presentation.study.today] 下按块拆开，
 * 本文件只负责数据口径与拼装。
 *
 * 数据口径：
 * - [StudyUiState.todayStudyMinutes] 是实际学习分钟数；
 * - DailyPlan.dailyGoalMinutes 是后端 canonical 日目标；
 * - 计划项预计总分钟是 planned，不等于 goal。
 */
@Composable
fun StudyTodayTab(
    uiState: StudyUiState,
    planUiState: StudyPlanUiState,
    onToggleItem: (PlanItem) -> Unit,
    onStartFocus: (PlanItem) -> Unit,
    onOpenPlanManager: () -> Unit
) {
    val items = planUiState.planItems
    val plannedMinutes = totalPlannedMinutes(items)
    val dailyGoalMinutes = planUiState.plan?.dailyGoalMinutes ?: 0
    val completed = items.count { it.isDone || it.status == "completed" }
    val nextItem = selectNextPlanItem(items)
    var detailItem by remember { mutableStateOf<PlanItem?>(null) }

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(top = 16.dp, bottom = 28.dp)
    ) {
        item {
            TodayProgress(
                actualMinutes = uiState.todayStudyMinutes,
                goalMinutes = dailyGoalMinutes,
                plannedMinutes = plannedMinutes,
                completedCount = completed,
                totalCount = items.size
            )
        }

        planUiState.error?.takeIf { it.isNotBlank() }?.let { message ->
            item {
                Text(
                    text = message,
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(bottom = 16.dp)
                )
            }
        }

        item {
            TodayNextTask(
                item = nextItem,
                onOpen = { nextItem?.let { detailItem = it } },
                onStart = { nextItem?.let(onStartFocus) }
            )
        }

        item {
            TodayTasksHeader(onOpenPlanManager = onOpenPlanManager)
        }

        if (items.isEmpty()) {
            item { EmptyPlanHint(onOpenPlanManager = onOpenPlanManager) }
        } else {
            items(items, key = { it.id.ifBlank { "${it.time}:${it.content}" } }) { item ->
                TodayTaskRow(
                    item = item,
                    onOpen = { detailItem = item },
                    onToggle = { onToggleItem(item) },
                    onStart = { onStartFocus(item) }
                )
            }
        }
    }

    detailItem?.let { item ->
        PlanItemDetailSheet(
            item = item,
            onDismiss = { detailItem = null },
            onToggle = {
                onToggleItem(item)
                detailItem = null
            },
            onStart = {
                onStartFocus(item)
                detailItem = null
            }
        )
    }
}

/** 「今日任务」标记 + 右侧管理入口：小字标签，不再抢主标题。 */
@Composable
private fun TodayTasksHeader(onOpenPlanManager: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 4.dp, bottom = 4.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = "今日任务",
            fontSize = 13.sp,
            color = TextTertiary
        )
        Row(
            modifier = Modifier
                .clip(RoundedCornerShape(10.dp))
                .clickable(onClick = onOpenPlanManager)
                .padding(horizontal = 6.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "管理计划",
                fontSize = 14.sp,
                fontWeight = FontWeight.Medium,
                color = TextSecondary
            )
            Icon(
                imageVector = Icons.Default.ChevronRight,
                contentDescription = null,
                tint = TextSecondary,
                modifier = Modifier.size(18.dp)
            )
        }
    }
}

@Composable
private fun EmptyPlanHint(onOpenPlanManager: () -> Unit) {
    Text(
        text = "今天还没有计划。可以先手动添加；自动 Planner 生成后会直接出现在这里。",
        fontSize = 14.sp,
        lineHeight = 23.sp,
        color = TextSecondary,
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 8.dp)
            .clickable(onClick = onOpenPlanManager)
    )
}

/** 下一项：进行中优先，其次第一个未完成且未跳过的任务。 */
internal fun selectNextPlanItem(items: List<PlanItem>): PlanItem? {
    return items.firstOrNull { it.status == "in_progress" }
        ?: items.firstOrNull {
            !it.isDone && it.status != "completed" && it.status != "skipped"
        }
}

internal fun totalPlannedMinutes(items: List<PlanItem>): Int =
    items.asSequence()
        .filter { it.status != "skipped" }
        .sumOf { it.estimatedDurationMinutes.coerceAtLeast(0) }

internal fun formatStudyMinutes(minutes: Int): String {
    val safe = minutes.coerceAtLeast(0)
    val hours = safe / 60
    val rest = safe % 60
    return when {
        hours <= 0 -> "${rest}min"
        rest == 0 -> "${hours}h"
        else -> "${hours}h ${rest}min"
    }
}
