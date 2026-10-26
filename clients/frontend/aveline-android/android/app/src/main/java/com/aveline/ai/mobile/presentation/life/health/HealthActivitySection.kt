package com.aveline.ai.mobile.presentation.life.health

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.health.daily.DailyDataUiState
import com.aveline.ai.mobile.presentation.life.LifeDivider
import com.aveline.ai.mobile.presentation.life.LifeFaint
import com.aveline.ai.mobile.presentation.life.LifeGroup
import com.aveline.ai.mobile.presentation.life.LifeInk
import com.aveline.ai.mobile.presentation.life.LifeMute
import com.aveline.ai.mobile.presentation.life.LifeTrackFaint
import com.aveline.ai.mobile.presentation.life.lifeCount
import com.aveline.ai.mobile.presentation.life.lifeDecimal

/** 活动格：22sp 数值 + 单位 + 说明。 */
private data class LifeActivityCell(
    val label: String,
    val value: String,
    val unit: String
)

/** 今日活动：四个次级数字 2×2，下面接运动会话。 */
@Composable
internal fun HealthActivitySection(state: DailyDataUiState) {
    val cells = listOfNotNull(
        state.activeCaloriesBurned?.takeIf { it > 0 }
            ?.let { LifeActivityCell("活动消耗", lifeCount(it), "kcal") },
        state.activeTimeMinutes?.takeIf { it > 0 }
            ?.let { LifeActivityCell("活动时长", it.toString(), "分钟") },
        state.totalDistanceKm?.takeIf { it > 0 }
            ?.let { LifeActivityCell("距离", lifeDecimal(it, 2), "km") },
        state.floorsClimbed?.takeIf { it > 0 }
            ?.let { LifeActivityCell("爬楼", lifeDecimal(it, 0), "层") }
    )
    if (cells.isEmpty() && state.exerciseSessions.isEmpty()) return

    LifeGroup(title = "今日活动", topSpacing = 32.dp, contentSpacing = 16.dp) {
        if (cells.isNotEmpty()) {
            Column {
                cells.chunked(2).forEachIndexed { index, rowCells ->
                    if (index > 0) Spacer(modifier = Modifier.height(18.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(16.dp)
                    ) {
                        rowCells.forEach { cell ->
                            ActivityCell(cell = cell, modifier = Modifier.weight(1f))
                        }
                        if (rowCells.size == 1) {
                            Spacer(modifier = Modifier.weight(1f))
                        }
                    }
                }
            }
        }
        if (state.exerciseSessions.isNotEmpty()) {
            if (cells.isNotEmpty()) Spacer(modifier = Modifier.height(16.dp))
            Column {
                state.exerciseSessions.forEach { session ->
                    LifeDivider(color = LifeTrackFaint)
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 12.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = session.exerciseTypeName + session.customTitle
                                ?.takeIf { it.isNotBlank() }
                                ?.let { " · $it" }
                                .orEmpty(),
                            style = TextStyle(fontSize = 15.sp, lineHeight = 20.sp, color = LifeInk),
                            modifier = Modifier.weight(1f)
                        )
                        Spacer(modifier = Modifier.width(12.dp))
                        Text(
                            text = "${session.durationMinutes} 分钟 · " +
                                lifeCount(session.calories.toDouble()) + " kcal",
                            style = TextStyle(
                                fontSize = 13.sp,
                                lineHeight = 18.sp,
                                color = LifeMute,
                                fontFeatureSettings = "tnum"
                            )
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ActivityCell(
    cell: LifeActivityCell,
    modifier: Modifier = Modifier
) {
    Column(modifier = modifier) {
        Row {
            Text(
                text = cell.value,
                style = TextStyle(
                    fontSize = 22.sp,
                    lineHeight = 26.sp,
                    fontWeight = FontWeight.Medium,
                    letterSpacing = (-0.5).sp,
                    color = LifeInk,
                    fontFeatureSettings = "tnum"
                ),
                modifier = Modifier.alignByBaseline()
            )
            Spacer(modifier = Modifier.width(4.dp))
            Text(
                text = cell.unit,
                style = TextStyle(fontSize = 12.5.sp, lineHeight = 17.sp, color = LifeFaint),
                modifier = Modifier.alignByBaseline()
            )
        }
        Spacer(modifier = Modifier.height(2.dp))
        Text(
            text = cell.label,
            style = TextStyle(fontSize = 12.5.sp, lineHeight = 17.sp, color = LifeFaint)
        )
    }
}
