package com.aveline.ai.mobile.presentation.companion

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.CharacterDailySlot
import com.aveline.ai.mobile.presentation.status.ui.StatusUiState
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.TextBody
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/** 时间列固定 48dp，圆点列 14dp：两列都不随文字宽度跳动，整页时间才对得齐 */
private val TimeColumnWidth = 48.dp
private val DotColumnWidth = 14.dp
private val TimelineGap = 10.dp

/** 日程项相对「现在」的位置 */
private enum class SlotTiming { PAST, CURRENT, FUTURE }

/**
 * Companion 日程 Tab。
 *
 * 一条时间线：左边等宽等距的时间（等宽字体，数字不跳），中间一个点，
 * 右边活动名。过去的整行变灰，正在做的那项加粗并显示细节，未来的点画成空心环。
 *
 * 原来每项是一张带圆角的 Surface 卡片、还带「已完成 / 正在进行 / 未开始 ·
 * 时间可调整」的第三行文字——状态本来就该由灰度和点表达，不需要再写一遍。
 */
@Composable
fun CompanionScheduleTab(uiState: StatusUiState) {
    val plan = uiState.lifeStatus?.dailyPlan
    val slots = plan?.slots.orEmpty()
    val currentIndex = slots.indexOfFirst { it.executionStatus == "in_progress" }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = CompanionGutter),
        contentPadding = PaddingValues(top = 14.dp, bottom = 24.dp)
    ) {
        item(key = "schedule-caption") {
            Text(
                text = planCaption(plan?.date.orEmpty(), slots.size),
                style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.5.sp),
                color = TextTertiary,
                modifier = Modifier.padding(start = 4.dp, bottom = 4.dp)
            )
        }

        when {
            uiState.isLoading && slots.isEmpty() -> item(key = "schedule-loading") {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 40.dp),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator(color = Accent, modifier = Modifier.size(22.dp), strokeWidth = 2.dp)
                }
            }

            slots.isEmpty() -> item(key = "schedule-empty") {
                Column(
                    modifier = Modifier.padding(vertical = 24.dp, horizontal = 4.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    Text(
                        text = "今日日程正在同步…",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextTertiary
                    )
                    uiState.lifeStatus?.let { status ->
                        Text(
                            text = "当前：${companionSlotLabel(plan?.activityLabel, status.activity)}",
                            style = MaterialTheme.typography.bodySmall,
                            color = TextTertiary
                        )
                    }
                }
            }

            else -> itemsIndexed(
                items = slots,
                key = { _, slot -> "${slot.activity}@${slot.plannedStart}" }
            ) { index, slot ->
                ScheduleTimelineRow(
                    slot = slot,
                    timing = timingOf(slot, index, currentIndex)
                )
            }
        }
    }
}

@Composable
private fun ScheduleTimelineRow(slot: CharacterDailySlot, timing: SlotTiming) {
    val timeColor = when (timing) {
        SlotTiming.CURRENT -> TextPrimary
        SlotTiming.PAST -> TextTertiary.copy(alpha = 0.55f)
        SlotTiming.FUTURE -> TextTertiary
    }
    val textColor = when (timing) {
        SlotTiming.CURRENT -> TextPrimary
        SlotTiming.PAST -> TextTertiary
        SlotTiming.FUTURE -> TextBody
    }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 46.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(TimelineGap)
    ) {
        Text(
            text = formatPlanTime(slot.plannedStart),
            modifier = Modifier.width(TimeColumnWidth),
            style = MaterialTheme.typography.labelMedium.copy(
                fontFamily = FontFamily.Monospace,
                fontSize = 12.sp
            ),
            color = timeColor,
            maxLines = 1
        )

        Box(
            modifier = Modifier.width(DotColumnWidth),
            contentAlignment = Alignment.Center
        ) {
            TimelineDot(timing = timing)
        }

        Column(
            modifier = Modifier
                .weight(1f)
                .padding(vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(1.dp)
        ) {
            Text(
                text = companionSlotLabel(slot.label, slot.activity),
                style = MaterialTheme.typography.bodyLarge.copy(
                    fontSize = 15.sp,
                    fontWeight = if (timing == SlotTiming.CURRENT) FontWeight.SemiBold else FontWeight.Normal
                ),
                color = textColor,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
            if (timing == SlotTiming.CURRENT && slot.detail.isNotBlank()) {
                Text(
                    text = slot.detail,
                    style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.5.sp),
                    color = TextTertiary,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
    }
}

/** 过去：实心深灰；现在：实心鼠尾草绿；未来：空心环 */
@Composable
private fun TimelineDot(timing: SlotTiming) {
    when (timing) {
        SlotTiming.CURRENT -> Box(
            modifier = Modifier
                .size(7.dp)
                .clip(CircleShape)
                .background(Accent)
        )
        SlotTiming.PAST -> Box(
            modifier = Modifier
                .size(7.dp)
                .clip(CircleShape)
                .background(Color(0xFF3A3A3C))
        )
        SlotTiming.FUTURE -> Box(
            modifier = Modifier
                .size(7.dp)
                .clip(CircleShape)
                .border(width = 1.5.dp, color = Color.White.copy(alpha = 0.3f), shape = CircleShape)
        )
    }
}

private fun timingOf(slot: CharacterDailySlot, index: Int, currentIndex: Int): SlotTiming = when {
    index == currentIndex -> SlotTiming.CURRENT
    slot.executionStatus == "completed" -> SlotTiming.PAST
    currentIndex >= 0 && index < currentIndex -> SlotTiming.PAST
    else -> SlotTiming.FUTURE
}

/** 顶部一行小字：日期 + 项数；缺日期时说明这是哪个角色的日程 */
private fun planCaption(date: String, slotCount: Int): String {
    val day = date.ifBlank { "今日" }
    return if (slotCount > 0) "$day · $slotCount 项" else day
}

private fun formatPlanTime(value: String): String {
    val time = value.substringAfter('T', value).substringBefore('+').substringBefore('Z')
    return time.take(5).ifBlank { "--:--" }
}

/** 展示名优先用后端下发的 label，仅在字段缺失（旧后端/暂无日程）时回退本地映射。 */
private fun companionSlotLabel(label: String?, activity: String?): String =
    label.orEmpty().ifBlank { companionActivityLabel(activity.orEmpty().ifBlank { "idle" }) }
