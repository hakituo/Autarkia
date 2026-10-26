package com.aveline.ai.mobile.presentation.life.health

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.health.daily.DailyDataUiState
import com.aveline.ai.mobile.presentation.life.LifeInk
import com.aveline.ai.mobile.presentation.life.LifeMute
import com.aveline.ai.mobile.presentation.life.LifeOnInk

/** 判断健康页是否存在可展示的数据（设备上下文不算健康数据）。 */
internal fun hasAnyHealthData(state: DailyDataUiState): Boolean =
    (state.steps ?: 0L) > 0L ||
        (state.heartRate ?: 0) > 0 ||
        (state.sleepMinutes ?: 0L) > 0L ||
        state.sleepScore != null ||
        state.sleepStartTime != null ||
        state.sleepEndTime != null ||
        state.sleepStageAwakeMinutes != null ||
        state.sleepStageLightMinutes != null ||
        state.sleepStageDeepMinutes != null ||
        state.sleepStageRemMinutes != null ||
        state.activeCaloriesBurned != null ||
        state.activeTimeMinutes != null ||
        state.totalDistanceKm != null ||
        state.floorsClimbed != null ||
        state.exerciseSessions.isNotEmpty() ||
        state.healthWeightKg != null ||
        state.weightKg != null ||
        state.bodyFatPercent != null ||
        state.bodyFatMass != null ||
        state.skeletalMusclePercent != null ||
        state.skeletalMuscleMass != null ||
        state.fatFreeMass != null ||
        state.totalBodyWater != null ||
        state.heightM != null ||
        state.skinTemperature != null ||
        state.bloodOxygen != null ||
        state.energyScore != null ||
        state.sleepApneaSign != null ||
        state.irregularHeartRhythmStatus != null

/**
 * 空状态：替代整页 N/A。
 *
 * @param onConnect 请求 Samsung Health 授权并同步
 * @param onLater 收起空状态，退回「未同步」的一句话
 */
@Composable
internal fun HealthEmptyState(
    onConnect: () -> Unit,
    onLater: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 12.dp, end = 12.dp, top = 48.dp)
    ) {
        Text(
            text = "还没有健康数据",
            style = TextStyle(
                fontSize = 22.sp,
                lineHeight = 30.sp,
                fontWeight = FontWeight.SemiBold,
                letterSpacing = (-0.2).sp,
                color = LifeInk
            )
        )
        Spacer(modifier = Modifier.height(14.dp))
        Text(
            text = "步数、睡眠、心率从 Samsung Health 读取，手表的实时数据也走这里。授权一次，之后会自动同步。",
            style = TextStyle(fontSize = 14.5.sp, lineHeight = 26.sp, color = LifeMute)
        )
        Spacer(modifier = Modifier.height(28.dp))
        Button(
            onClick = onConnect,
            modifier = Modifier
                .fillMaxWidth()
                .height(48.dp),
            shape = RoundedCornerShape(14.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = LifeInk,
                contentColor = LifeOnInk
            )
        ) {
            Text(
                text = "连接 Samsung Health",
                style = TextStyle(fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
            )
        }
        TextButton(
            onClick = onLater,
            modifier = Modifier
                .fillMaxWidth()
                .height(44.dp)
        ) {
            Text(
                text = "稍后",
                style = TextStyle(fontSize = 15.sp, fontWeight = FontWeight.Medium),
                color = LifeMute
            )
        }
    }
}
