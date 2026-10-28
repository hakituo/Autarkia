package com.aveline.ai.mobile.presentation.study.focus

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.study.StudyFocusState
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 专注页底部：未开始时是三个紧凑步进器，开始后收起换成三格统计。
 *
 * 原实现是三行 OutlinedButton「−/+」，占满下半屏；现在压成一排，
 * 一旦开始计时（含暂停）就整块让位给「今日番茄 / 本轮 / 到长休息」，重置后回到步进器。
 */
@Composable
internal fun FocusBottomPanel(
    state: StudyFocusState,
    showStats: Boolean,
    onWorkMinutesChange: (Int) -> Unit,
    onBreakMinutesChange: (Int) -> Unit,
    onLongBreakMinutesChange: (Int) -> Unit,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(bottom = 22.dp)
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(Line)
        )
        Box(modifier = Modifier.padding(top = 16.dp)) {
            if (showStats) {
                RunningStats(state)
            } else {
                DurationRow(
                    state = state,
                    onWorkMinutesChange = onWorkMinutesChange,
                    onBreakMinutesChange = onBreakMinutesChange,
                    onLongBreakMinutesChange = onLongBreakMinutesChange
                )
            }
        }
    }
}

@Composable
private fun RunningStats(state: StudyFocusState) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceEvenly
    ) {
        StatCell(value = "${state.todayTomatoes}", label = "今日番茄")
        StatCell(
            value = focusRoundText(state.completedCycles, state.cyclesBeforeLongBreak, state.phase),
            label = "本轮"
        )
        StatCell(
            value = "${focusCyclesToLongBreak(state.completedCycles, state.cyclesBeforeLongBreak, state.phase)}",
            label = "到长休息"
        )
    }
}

@Composable
private fun StatCell(value: String, label: String) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        Text(
            text = value,
            fontSize = 22.sp,
            fontWeight = FontWeight.Medium,
            color = TextPrimary
        )
        Text(
            text = label,
            fontSize = 12.sp,
            color = TextTertiary
        )
    }
}

@Composable
private fun DurationRow(
    state: StudyFocusState,
    onWorkMinutesChange: (Int) -> Unit,
    onBreakMinutesChange: (Int) -> Unit,
    onLongBreakMinutesChange: (Int) -> Unit
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        DurationStepper(
            label = "专注",
            value = state.workMinutes,
            onValueChange = onWorkMinutesChange,
            modifier = Modifier.weight(1f)
        )
        DurationStepper(
            label = "短休息",
            value = state.breakMinutes,
            onValueChange = onBreakMinutesChange,
            modifier = Modifier.weight(1f)
        )
        DurationStepper(
            label = "长休息",
            value = state.longBreakMinutes,
            onValueChange = onLongBreakMinutesChange,
            modifier = Modifier.weight(1f)
        )
    }
}

@Composable
private fun DurationStepper(
    label: String,
    value: Int,
    onValueChange: (Int) -> Unit,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Text(
            text = label,
            fontSize = 12.sp,
            color = TextTertiary
        )
        Row(
            modifier = Modifier
                .height(36.dp)
                .clip(RoundedCornerShape(12.dp))
                .border(1.dp, Color(0x1FFFFFFF), RoundedCornerShape(12.dp)),
            verticalAlignment = Alignment.CenterVertically
        ) {
            StepperButton(
                icon = Icons.Default.Remove,
                contentDescription = "$label 减少",
                enabled = value > 1,
                onClick = { onValueChange((value - 1).coerceAtLeast(1)) }
            )
            Box(
                modifier = Modifier.width(26.dp),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = value.toString(),
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Medium,
                    color = TextPrimary
                )
            }
            StepperButton(
                icon = Icons.Default.Add,
                contentDescription = "$label 增加",
                enabled = value < 120,
                onClick = { onValueChange((value + 1).coerceAtMost(120)) }
            )
        }
    }
}

@Composable
private fun StepperButton(
    icon: ImageVector,
    contentDescription: String,
    enabled: Boolean,
    onClick: () -> Unit
) {
    Box(
        modifier = Modifier
            .width(30.dp)
            .fillMaxHeight()
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center
    ) {
        Icon(
            imageVector = icon,
            contentDescription = contentDescription,
            tint = if (enabled) TextTertiary else Color(0x3DFFFFFF),
            modifier = Modifier.size(16.dp)
        )
    }
}
