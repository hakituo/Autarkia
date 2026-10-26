package com.aveline.ai.mobile.presentation.life

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.health.daily.DailyDataUiState
import com.aveline.ai.mobile.presentation.life.health.HealthActivitySection
import com.aveline.ai.mobile.presentation.life.health.HealthBodySection
import com.aveline.ai.mobile.presentation.life.health.HealthDeviceSection
import com.aveline.ai.mobile.presentation.life.health.HealthEmptyState
import com.aveline.ai.mobile.presentation.life.health.HealthHeroSection
import com.aveline.ai.mobile.presentation.life.health.HealthOtherSection
import com.aveline.ai.mobile.presentation.life.health.HealthSleepSection
import com.aveline.ai.mobile.presentation.life.health.hasAnyHealthData

/**
 * Life - 健康 Tab。
 *
 * 设计稿口径：先给结论再给细节——顶部三个大数字（睡眠/步数/心率），
 * 往下按主题分组，没有数据的行不出现；整页无数据时展示空状态而不是 N/A。
 *
 * 数据来源：
 * - 实时数据（心率）：手表端 Health Services via Wearable Data Layer
 * - 历史数据（睡眠/身体成分/活动）：Samsung Health Data SDK
 *
 * @param uiState 日常生活数据状态
 * @param onSyncSamsungHealth 请求 Samsung Health 授权并同步（需要 Activity）
 */
@Composable
fun LifeHealthTab(
    uiState: DailyDataUiState,
    onSyncSamsungHealth: () -> Unit
) {
    // 用户点「稍后」后本次进入不再显示空状态，退回一句话的未同步提示。
    var emptyDismissed by rememberSaveable { mutableStateOf(false) }

    Column(modifier = Modifier.fillMaxWidth()) {
        if (!hasAnyHealthData(uiState)) {
            if (emptyDismissed) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 24.dp)
                ) {
                    LifeMissing("未同步：步数、睡眠、心率、身体成分。")
                    TextButton(onClick = onSyncSamsungHealth) {
                        Text(
                            text = "连接 Samsung Health",
                            style = TextStyle(fontSize = 15.sp),
                            color = LifeInk
                        )
                    }
                }
            } else {
                HealthEmptyState(
                    onConnect = onSyncSamsungHealth,
                    onLater = { emptyDismissed = true }
                )
            }
            return@Column
        }

        HealthHeroSection(uiState)
        HealthSleepSection(uiState)
        HealthActivitySection(uiState)
        HealthBodySection(uiState)
        HealthOtherSection(uiState)
        HealthDeviceSection(uiState)
    }
}
