package com.aveline.ai.mobile.presentation.life.health

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.health.daily.DailyDataUiState
import com.aveline.ai.mobile.presentation.life.LifeFaint
import com.aveline.ai.mobile.presentation.life.LifeGroup
import com.aveline.ai.mobile.presentation.life.LifeHeroStat
import com.aveline.ai.mobile.presentation.life.LifeInk
import com.aveline.ai.mobile.presentation.life.LifeMissing
import com.aveline.ai.mobile.presentation.life.LifeMonoStyle
import com.aveline.ai.mobile.presentation.life.LifeMute
import com.aveline.ai.mobile.presentation.life.LifeSleepAwake
import com.aveline.ai.mobile.presentation.life.LifeSleepDeep
import com.aveline.ai.mobile.presentation.life.LifeSleepRem
import com.aveline.ai.mobile.presentation.life.LifeValueStyle
import com.aveline.ai.mobile.presentation.life.lifeClock
import com.aveline.ai.mobile.presentation.life.lifeCount
import com.aveline.ai.mobile.presentation.life.lifeDuration
import com.aveline.ai.mobile.presentation.theme.LifeEnergy

/** 顶部三个大数字：睡眠 / 步数 / 心率，没值的直接不出现。 */
@Composable
internal fun HealthHeroSection(state: DailyDataUiState) {
    val cells = buildList {
        lifeDuration(state.sleepMinutes)?.let { add(Triple("睡眠", it, "")) }
        state.steps?.takeIf { it > 0 }?.let { add(Triple("步数", lifeCount(it), "")) }
        state.heartRate?.takeIf { it > 0 }?.let { add(Triple("心率", it.toString(), "bpm")) }
    }
    if (cells.isEmpty()) return

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 22.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        cells.forEach { (label, value, unit) ->
            LifeHeroStat(
                label = label,
                value = value,
                unit = unit,
                modifier = Modifier.weight(1f)
            )
        }
    }
}

/** 睡眠阶段（分钟数与图形颜色）。 */
private data class LifeSleepStage(
    val label: String,
    val minutes: Long,
    val color: Color
)

/** 睡眠：得分 + 分段条 + 起止时间 + 四格阶段。 */
@Composable
internal fun HealthSleepSection(state: DailyDataUiState) {
    val stages = listOfNotNull(
        state.sleepStageDeepMinutes?.takeIf { it > 0 }
            ?.let { LifeSleepStage("深睡", it, LifeSleepDeep) },
        state.sleepStageLightMinutes?.takeIf { it > 0 }
            ?.let { LifeSleepStage("浅睡", it, LifeEnergy) },
        state.sleepStageRemMinutes?.takeIf { it > 0 }
            ?.let { LifeSleepStage("REM", it, LifeSleepRem) },
        state.sleepStageAwakeMinutes?.takeIf { it > 0 }
            ?.let { LifeSleepStage("清醒", it, LifeSleepAwake) }
    )
    val startClock = lifeClock(state.sleepStartTime)
    val endClock = lifeClock(state.sleepEndTime)
    val hasSleep = stages.isNotEmpty() || (state.sleepMinutes ?: 0L) > 0L ||
        state.sleepScore != null || startClock != null || endClock != null
    if (!hasSleep) return

    LifeGroup(
        title = "睡眠",
        topSpacing = 32.dp,
        trailing = {
            state.sleepScore?.let { score ->
                Row {
                    Text(
                        text = "得分 ",
                        style = TextStyle(fontSize = 13.sp, lineHeight = 18.sp, color = LifeMute),
                        modifier = Modifier.alignByBaseline()
                    )
                    Text(
                        text = score.toString(),
                        style = TextStyle(
                            fontSize = 15.sp,
                            lineHeight = 20.sp,
                            fontWeight = FontWeight.Medium,
                            color = LifeInk,
                            fontFeatureSettings = "tnum"
                        ),
                        modifier = Modifier.alignByBaseline()
                    )
                }
            }
        }
    ) {
        if (stages.isNotEmpty()) {
            SleepStageBar(stages = stages)
            Spacer(modifier = Modifier.height(14.dp))
        }
        if (startClock != null || endClock != null) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(text = startClock?.let { "$it 入睡" } ?: "", style = LifeMonoStyle)
                Text(text = endClock?.let { "$it 起床" } ?: "", style = LifeMonoStyle)
            }
            Spacer(modifier = Modifier.height(12.dp))
        }
        if (stages.isNotEmpty()) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                stages.forEach { stage ->
                    SleepStageCell(stage = stage, modifier = Modifier.weight(1f))
                }
            }
        } else {
            LifeMissing("睡眠分期未同步。")
        }
    }
}

/** 一条圆角分段条，各阶段宽度按时长分配。 */
@Composable
private fun SleepStageBar(stages: List<LifeSleepStage>) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(10.dp)
            .clip(RoundedCornerShape(5.dp)),
        horizontalArrangement = Arrangement.spacedBy(2.dp)
    ) {
        stages.forEach { stage ->
            Box(
                modifier = Modifier
                    .weight(stage.minutes.toFloat())
                    .fillMaxHeight()
                    .background(stage.color)
            )
        }
    }
}

/** 单个阶段：颜色块 + 名称 + 时长。 */
@Composable
private fun SleepStageCell(
    stage: LifeSleepStage,
    modifier: Modifier = Modifier
) {
    Column(modifier = modifier) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .background(stage.color, RoundedCornerShape(2.dp))
            )
            Spacer(modifier = Modifier.width(6.dp))
            Text(
                text = stage.label,
                style = TextStyle(fontSize = 12.sp, lineHeight = 16.sp, color = LifeFaint)
            )
        }
        Spacer(modifier = Modifier.height(4.dp))
        Text(text = lifeDuration(stage.minutes).orEmpty(), style = LifeValueStyle)
    }
}
