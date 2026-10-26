package com.aveline.ai.mobile.presentation.life

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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.data.samsung.WaterIntakeEntry
import com.aveline.ai.mobile.presentation.health.daily.DailyDataUiState
import com.aveline.ai.mobile.presentation.theme.LifeEnergy

/** 饮水目标兜底值（毫升）；Samsung Health 有目标时优先用下发的目标。 */
private const val DEFAULT_WATER_GOAL_ML = 2000

/**
 * Life - 饮水 Tab。
 *
 * 设计稿口径：一个大数字 + 一条进度，下面按时间列出每次记录；
 * 不再用 SectionCard，也不显示 N/A——没有记录时只留一句「未同步」。
 *
 * @param uiState 日常生活数据状态
 */
@Composable
fun LifeWaterTab(
    uiState: DailyDataUiState
) {
    val entries = uiState.waterIntakeEntries.sortedBy { it.startTime }
    val entryTotalMl = entries.sumOf { it.amountMl.toInt() }
    val aggregateTotalMl = uiState.waterIntakeMl?.toInt()?.takeIf { it > 0 }
    val totalMl = if (entries.isNotEmpty()) entryTotalMl else aggregateTotalMl ?: 0
    val hasData = entries.isNotEmpty() || aggregateTotalMl != null
    val goalMl = uiState.waterIntakeGoalMl?.toInt()?.takeIf { it > 0 } ?: DEFAULT_WATER_GOAL_ML
    val progress = (totalMl.toFloat() / goalMl).coerceIn(0f, 1f)
    val remainingMl = (goalMl - totalMl).coerceAtLeast(0)

    Column(modifier = Modifier.fillMaxWidth()) {
        if (!hasData) {
            LifeMissing(
                text = "未同步：今日饮水记录。",
                modifier = Modifier.padding(top = 36.dp)
            )
            return@Column
        }

        // 今日饮水：一个大数字 + 一条进度
        Column(modifier = Modifier.padding(top = 36.dp)) {
            Text(text = "今日饮水", style = LifeGroupLabelStyle)
            Spacer(modifier = Modifier.height(16.dp))
            LifeBigValue(
                value = lifeCount(totalMl.toLong()),
                unit = "/ ${lifeCount(goalMl.toLong())} ml"
            )
            Spacer(modifier = Modifier.height(16.dp))
            WaterProgressBar(progress = progress)
            Spacer(modifier = Modifier.height(12.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = if (entries.isNotEmpty()) "${entries.size} 次" else "",
                    style = LifeSecondaryStyle
                )
                Text(
                    text = if (remainingMl > 0) {
                        "还差 ${lifeCount(remainingMl.toLong())} ml"
                    } else {
                        "已达标"
                    },
                    style = LifeSecondaryStyle
                )
            }
        }

        // 记录：时间 / 相对量条 / 毫升数，去掉灰底块
        LifeGroup(title = "记录", topSpacing = 28.dp) {
            Column {
                if (entries.isEmpty()) {
                    LifeMissing("未同步：逐条饮水记录。")
                } else {
                    val maxAmountMl = entries.maxOf { it.amountMl }.coerceAtLeast(1f)
                    entries.forEach { entry ->
                        WaterRecordRow(entry = entry, maxAmountMl = maxAmountMl)
                    }
                }
                Spacer(modifier = Modifier.height(14.dp))
                Text(text = "来自 Samsung Health", style = LifeSecondaryStyle)
            }
        }
    }
}

/** 今日饮水进度条：6dp 圆角，Life 雾蓝填充。 */
@Composable
private fun WaterProgressBar(progress: Float) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(6.dp)
            .clip(RoundedCornerShape(3.dp))
            .background(LifeTrack)
    ) {
        if (progress > 0f) {
            Box(
                modifier = Modifier
                    .fillMaxHeight()
                    .fillMaxWidth(progress)
                    .background(LifeEnergy)
            )
        }
    }
}

/** 单条饮水记录：时间占 56dp，量条按当日最大一次折算，右侧毫升数。 */
@Composable
private fun WaterRecordRow(
    entry: WaterIntakeEntry,
    maxAmountMl: Float
) {
    val ratio = (entry.amountMl / maxAmountMl).coerceIn(0f, 1f)
    Column {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 13.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = lifeClock(entry.startTime.toEpochMilli()) ?: "--:--",
                style = LifeMonoStyle.copy(
                    fontSize = 13.sp,
                    lineHeight = 18.sp,
                    color = LifeMute
                ),
                modifier = Modifier.width(56.dp),
                maxLines = 1
            )
            Box(
                modifier = Modifier
                    .weight(1f)
                    .height(4.dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(LifeTrackFaint)
            ) {
                if (ratio > 0f) {
                    Box(
                        modifier = Modifier
                            .fillMaxHeight()
                            .fillMaxWidth(ratio)
                            .background(LifeEnergy.copy(alpha = 0.7f))
                    )
                }
            }
            Spacer(modifier = Modifier.width(12.dp))
            Text(
                text = "${lifeCount(entry.amountMl.toDouble())} ml",
                style = LifeValueStyle,
                modifier = Modifier.width(64.dp),
                textAlign = TextAlign.End
            )
        }
        LifeDivider(color = LifeTrackFaint)
    }
}
