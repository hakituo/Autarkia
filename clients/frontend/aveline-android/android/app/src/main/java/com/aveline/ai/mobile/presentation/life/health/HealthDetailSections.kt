package com.aveline.ai.mobile.presentation.life.health

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.BatteryChargingFull
import androidx.compose.material.icons.filled.BatteryFull
import androidx.compose.material.icons.filled.LightMode
import androidx.compose.material.icons.filled.SignalCellularAlt
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.NetworkType
import com.aveline.ai.mobile.presentation.health.daily.DailyDataUiState
import com.aveline.ai.mobile.presentation.life.LifeChip
import com.aveline.ai.mobile.presentation.life.LifeFaint
import com.aveline.ai.mobile.presentation.life.LifeGroup
import com.aveline.ai.mobile.presentation.life.LifeInk
import com.aveline.ai.mobile.presentation.life.LifeMissing
import com.aveline.ai.mobile.presentation.life.LifeRow
import com.aveline.ai.mobile.presentation.life.lifeDecimal
import com.aveline.ai.mobile.presentation.life.lifePercent

/** 身体成分：体重做大数字，其余明细行只列有值的。 */
@Composable
internal fun HealthBodySection(state: DailyDataUiState) {
    val weight = state.healthWeightKg ?: state.weightKg
    val bmi = computeLifeBmi(state.healthWeightKg ?: state.weightKg, state.heightM)
    val rows = listOfNotNull(
        state.bodyFatPercent?.let { "体脂率" to lifePercent(it) },
        state.bodyFatMass?.let { "脂肪量" to "${lifeDecimal(it, 1)} kg" },
        state.skeletalMusclePercent?.let { "骨骼肌率" to lifePercent(it) },
        state.skeletalMuscleMass?.let { "骨骼肌量" to "${lifeDecimal(it, 1)} kg" },
        state.fatFreeMass?.let { "去脂体重" to "${lifeDecimal(it, 1)} kg" },
        state.totalBodyWater?.let { "总体水分" to "${lifeDecimal(it, 1)} kg" },
        state.heightM?.let { "身高" to "${lifeDecimal(it, 2)} m" },
        bmi?.let { "BMI" to lifeDecimal(it, 1) }
    )
    if (weight == null && rows.isEmpty()) return

    LifeGroup(
        title = "身体成分",
        topSpacing = 32.dp,
        contentSpacing = 6.dp,
        trailing = {
            Text(
                text = "最近一次",
                style = TextStyle(fontSize = 12.sp, lineHeight = 16.sp, color = LifeFaint)
            )
        }
    ) {
        if (weight != null) {
            Row(verticalAlignment = Alignment.Bottom) {
                Text(
                    text = lifeDecimal(weight, 1),
                    style = TextStyle(
                        fontSize = 30.sp,
                        lineHeight = 34.sp,
                        fontWeight = FontWeight.Medium,
                        letterSpacing = (-1).sp,
                        color = LifeInk,
                        fontFeatureSettings = "tnum"
                    ),
                    modifier = Modifier.alignByBaseline()
                )
                Spacer(modifier = Modifier.width(4.dp))
                Text(
                    text = "kg",
                    style = TextStyle(fontSize = 13.sp, lineHeight = 18.sp, color = LifeFaint),
                    modifier = Modifier.alignByBaseline()
                )
            }
            Spacer(modifier = Modifier.height(8.dp))
        }
        Column {
            rows.forEach { (label, value) ->
                LifeRow(label = label, value = value)
            }
        }
    }
}

/** 零碎指标 + 健康预警：缺的写一句「未同步」，预警无异常时只写一句。 */
@Composable
internal fun HealthOtherSection(state: DailyDataUiState) {
    val rows = listOfNotNull(
        state.bloodOxygen?.let { "血氧饱和度" to lifePercent(it) },
        state.skinTemperature?.let { "皮肤温度" to "${lifeDecimal(it, 1)} °C" },
        state.energyScore?.let { "能量评分" to lifeDecimal(it, 0) }
    )
    val missing = listOfNotNull(
        if (state.bloodOxygen == null) "血氧" else null,
        if (state.skinTemperature == null) "皮肤温度" else null,
        if (state.energyScore == null) "能量评分" else null
    )
    val warnings = listOfNotNull(
        state.sleepApneaSign?.takeIf { !isLifeSignBenign(it) }
            ?.let { "睡眠呼吸暂停征兆" to lifeSignLabel(it) },
        state.irregularHeartRhythmStatus?.takeIf { !isLifeSignBenign(it) }
            ?.let { "心律不齐" to lifeSignLabel(it) }
    )
    val notes = buildList {
        if (missing.isNotEmpty()) add("未同步：${missing.joinToString("、")}。")
        if (warnings.isEmpty()) add("健康预警无异常。")
    }

    LifeGroup(title = "其他", topSpacing = 32.dp, contentSpacing = 10.dp) {
        Column(
            modifier = Modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            if (rows.isNotEmpty()) {
                Column {
                    rows.forEach { (label, value) ->
                        LifeRow(label = label, value = value)
                    }
                }
            }
            if (warnings.isNotEmpty()) {
                Column {
                    warnings.forEach { (label, value) ->
                        LifeRow(label = label, value = value)
                    }
                }
            }
            if (notes.isNotEmpty()) {
                LifeMissing(text = notes.joinToString(""))
            }
        }
    }
}

/** 设备上下文：底部一排小标签，它是 Agent 的上下文而不是用户主要看的数据。 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun HealthDeviceSection(state: DailyDataUiState) {
    val chips = buildList {
        state.batteryLevel?.let { level ->
            add(
                LifeDeviceChip(
                    icon = if (state.isCharging) {
                        Icons.Default.BatteryChargingFull
                    } else {
                        Icons.Default.BatteryFull
                    },
                    text = if (state.isCharging) "$level% 充电中" else "$level%"
                )
            )
        }
        if (state.networkType != NetworkType.UNKNOWN) {
            add(
                LifeDeviceChip(
                    icon = if (state.networkType == NetworkType.WIFI) {
                        Icons.Default.Wifi
                    } else {
                        Icons.Default.SignalCellularAlt
                    },
                    text = formatNetworkType(state.networkType)
                )
            )
        }
        state.screenBrightness?.let { level ->
            add(LifeDeviceChip(Icons.Default.LightMode, "亮度 $level/255"))
        }
        state.volumeLevel?.let { level ->
            add(LifeDeviceChip(Icons.AutoMirrored.Filled.VolumeUp, "音量 $level"))
        }
    }
    if (chips.isEmpty()) return

    LifeGroup(title = "这台手机", topSpacing = 32.dp, contentSpacing = 12.dp) {
        FlowRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            chips.forEach { chip ->
                LifeChip(icon = chip.icon, text = chip.text)
            }
        }
    }
}

/** 设备标签数据。 */
private data class LifeDeviceChip(
    val icon: ImageVector,
    val text: String
)

/** 计算 BMI（体重 kg / 身高 m²）。 */
private fun computeLifeBmi(weightKg: Double?, heightM: Double?): Double? {
    if (weightKg == null || heightM == null || heightM <= 0) return null
    return weightKg / (heightM * heightM)
}

/** 三星健康预警枚举名转中文；未知值原样展示。 */
private fun lifeSignLabel(raw: String): String = when (raw.uppercase()) {
    "NONE" -> "无异常"
    "NORMAL" -> "正常"
    "POSSIBLE" -> "可能有征兆"
    "DETECTED" -> "检测到异常"
    "HIGH" -> "偏高"
    "LOW" -> "偏低"
    "UNKNOWN" -> "未知"
    else -> raw
}

/** 仅把明确的正常值视为无预警；未知值宁可展示出来。 */
private fun isLifeSignBenign(raw: String): Boolean =
    raw.uppercase() == "NONE" || raw.uppercase() == "NORMAL"

/** 网络类型枚举转中文显示。 */
private fun formatNetworkType(type: NetworkType): String = when (type) {
    NetworkType.WIFI -> "WiFi"
    NetworkType.CELLULAR_2G -> "2G"
    NetworkType.CELLULAR_3G -> "3G"
    NetworkType.CELLULAR_4G -> "4G"
    NetworkType.CELLULAR_5G -> "5G"
    NetworkType.ETHERNET -> "以太网"
    NetworkType.BLUETOOTH -> "蓝牙"
    NetworkType.OFFLINE -> "离线"
    else -> "未知"
}
