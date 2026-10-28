package com.aveline.ai.mobile.presentation.study.today

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.study.formatStudyMinutes
import com.aveline.ai.mobile.presentation.theme.AvelineTextStyles
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 今日进度：不再包彩色卡片。
 *
 * 一个大数字（已学 / 目标）+ 4dp 细进度条 + 一行补充。
 * 进度条用正文色的中性白：达成目标也不变绿 —— 颜色只用来区分阶段，不用来发奖励。
 */
@Composable
internal fun TodayProgress(
    actualMinutes: Int,
    goalMinutes: Int,
    plannedMinutes: Int,
    completedCount: Int,
    totalCount: Int
) {
    val progress = if (goalMinutes > 0) {
        (actualMinutes.toFloat() / goalMinutes.toFloat()).coerceIn(0f, 1f)
    } else {
        0f
    }
    val remaining = (goalMinutes - actualMinutes).coerceAtLeast(0)
    val plannedText = formatPlanSpan(plannedMinutes)
    val summary = when {
        goalMinutes > 0 && remaining == 0 -> "已达成目标 · 计划共 $plannedText"
        goalMinutes > 0 -> "还差 ${formatStudyMinutes(remaining)} · 计划共 $plannedText"
        plannedMinutes > 0 -> "计划共 $plannedText"
        else -> "今天还没有计划"
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.Bottom
        ) {
            Row(
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalAlignment = Alignment.Bottom
            ) {
                Text(
                    text = formatStudyMinutes(actualMinutes),
                    style = AvelineTextStyles.studyMoment
                )
                Text(
                    text = if (goalMinutes > 0) "/ ${formatStudyMinutes(goalMinutes)} 目标" else "已学",
                    fontSize = 15.sp,
                    color = TextTertiary,
                    modifier = Modifier.padding(bottom = 5.dp)
                )
            }
            Text(
                text = "$completedCount / $totalCount 项",
                fontSize = 13.sp,
                color = TextTertiary,
                modifier = Modifier.padding(bottom = 5.dp)
            )
        }

        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(4.dp)
                .clip(RoundedCornerShape(2.dp))
                .background(Line)
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(progress)
                    .fillMaxHeight()
                    .clip(RoundedCornerShape(2.dp))
                    .background(TextPrimary)
            )
        }

        Text(
            text = summary,
            fontSize = 12.5f.sp,
            color = TextTertiary
        )
    }
}
