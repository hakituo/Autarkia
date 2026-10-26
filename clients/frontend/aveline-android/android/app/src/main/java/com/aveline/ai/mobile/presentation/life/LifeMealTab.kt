package com.aveline.ai.mobile.presentation.life

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.data.samsung.NutritionEntry
import com.aveline.ai.mobile.presentation.health.daily.DailyDataUiState
import com.aveline.ai.mobile.presentation.theme.LifeHunger

/** 餐食宏量（克数与图形颜色）。 */
private data class LifeMacro(
    val label: String,
    val grams: Double,
    val color: Color
)

/**
 * Life - 餐食 Tab。
 *
 * 设计稿口径：一个大热量数字 + 一条宏量分段条；每餐一行三层（餐次时间热量 / 菜名 / 宏量），
 * 微量营养素合并成两列细线列表，只列有值的。
 *
 * @param uiState 日常生活数据状态
 */
@Composable
fun LifeMealTab(
    uiState: DailyDataUiState
) {
    val aiNutritionEntries = uiState.nutritionEntries.filter { it.source.startsWith("ai_photo") }
    fun totalWithAi(base: Double?, value: (NutritionEntry) -> Float?): Double? {
        val aiValues = aiNutritionEntries.mapNotNull(value)
        if (base == null && aiValues.isEmpty()) return null
        return (base ?: 0.0) + aiValues.sumOf { it.toDouble() }
    }

    val totalCalories = totalWithAi(uiState.nutritionCalories) { it.calories }
    val totalProtein = totalWithAi(uiState.nutritionProtein) { it.protein }
    val totalCarbs = totalWithAi(uiState.nutritionCarbs) { it.carbs }
    val totalFat = totalWithAi(uiState.nutritionFat) { it.fat }
    val totalSaturatedFat = totalWithAi(uiState.nutritionSaturatedFat) { it.saturatedFat }
    val totalTransFat = totalWithAi(uiState.nutritionTransFat) { it.transFat }
    val totalFiber = totalWithAi(uiState.nutritionDietaryFiber) { it.dietaryFiber }
    val totalSugar = totalWithAi(uiState.nutritionSugar) { it.sugar }
    val totalCholesterol = totalWithAi(uiState.nutritionCholesterol) { it.cholesterol }
    val totalSodium = totalWithAi(uiState.nutritionSodium) { it.sodium }
    val totalPotassium = totalWithAi(uiState.nutritionPotassium) { it.potassium }
    val totalVitaminA = totalWithAi(uiState.nutritionVitaminA) { it.vitaminA }
    val totalVitaminC = totalWithAi(uiState.nutritionVitaminC) { it.vitaminC }
    val totalCalcium = totalWithAi(uiState.nutritionCalcium) { it.calcium }
    val totalIron = totalWithAi(uiState.nutritionIron) { it.iron }

    val entries = uiState.nutritionEntries.sortedBy { it.startTime }
    val macros = listOfNotNull(
        totalProtein?.takeIf { it > 0 }?.let { LifeMacro("蛋白质", it, LifeHunger) },
        totalCarbs?.takeIf { it > 0 }?.let { LifeMacro("碳水", it, LifeMacroLight) },
        totalFat?.takeIf { it > 0 }?.let { LifeMacro("脂肪", it, LifeMacroDark) }
    )
    val micros = listOfNotNull<Pair<String, String>>(
        totalFiber?.let { "膳食纤维" to "${lifeGram(it)} g" },
        totalSugar?.let { "糖" to "${lifeGram(it)} g" },
        totalSodium?.let { "钠" to "${lifeCount(it)} mg" },
        totalPotassium?.let { "钾" to "${lifeCount(it)} mg" },
        totalCalcium?.let { "钙" to "${lifeCount(it)} mg" },
        totalIron?.let { "铁" to "${lifeGram(it)} mg" },
        totalVitaminC?.let { "维C" to "${lifeGram(it)} mg" },
        totalCholesterol?.let { "胆固醇" to "${lifeCount(it)} mg" },
        totalSaturatedFat?.let { "饱和脂肪" to "${lifeGram(it)} g" },
        totalTransFat?.let { "反式脂肪" to "${lifeGram(it)} g" },
        totalVitaminA?.let { "维A" to "${lifeCount(it)} μg" }
    )
    val hasData = totalCalories != null || entries.isNotEmpty() ||
        macros.isNotEmpty() || micros.isNotEmpty()

    Column(modifier = Modifier.fillMaxWidth()) {
        if (!hasData) {
            LifeMissing(
                text = "未同步：今日餐食记录。",
                modifier = Modifier.padding(top = 36.dp)
            )
            return@Column
        }

        // 今日摄入：一个大数字 + 宏量分段条 + 三格明细
        Column(modifier = Modifier.padding(top = 30.dp)) {
            Text(text = "今日摄入", style = LifeGroupLabelStyle)
            Spacer(modifier = Modifier.height(16.dp))
            if (totalCalories != null) {
                LifeBigValue(value = lifeCount(totalCalories), unit = "kcal")
            } else {
                LifeMissing("未同步：今日摄入热量。")
            }
            if (macros.isNotEmpty()) {
                Spacer(modifier = Modifier.height(16.dp))
                MacroBar(macros = macros)
                Spacer(modifier = Modifier.height(16.dp))
                MacroGrid(macros = macros)
            }
        }

        // 记录：每餐三层，AI 估算用沙金描边小标签
        if (entries.isNotEmpty()) {
            LifeGroup(title = "记录", topSpacing = 30.dp, contentSpacing = 4.dp) {
                Column {
                    entries.forEach { entry ->
                        MealRow(entry = entry)
                        LifeDivider(color = LifeTrackFaint)
                    }
                }
            }
        }

        // 其他营养素：两列细线列表，只列有值的
        if (micros.isNotEmpty()) {
            Column(modifier = Modifier.padding(top = 28.dp)) {
                Text(text = "其他营养素", style = LifeGroupLabelStyle)
                Spacer(modifier = Modifier.height(6.dp))
                MicroGrid(items = micros)
            }
        }
    }
}

/** 三大营养素分段条：按克数分配宽度。 */
@Composable
private fun MacroBar(macros: List<LifeMacro>) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(8.dp)
            .clip(RoundedCornerShape(4.dp)),
        horizontalArrangement = Arrangement.spacedBy(2.dp)
    ) {
        macros.forEach { macro ->
            Box(
                modifier = Modifier
                    .weight(macro.grams.toFloat())
                    .fillMaxHeight()
                    .background(macro.color)
            )
        }
    }
}

/** 三格宏量明细：色块 + 名称 + 克数。 */
@Composable
private fun MacroGrid(macros: List<LifeMacro>) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        macros.forEach { macro ->
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        modifier = Modifier
                            .width(8.dp)
                            .height(8.dp)
                            .background(macro.color, RoundedCornerShape(2.dp))
                    )
                    Spacer(modifier = Modifier.width(6.dp))
                    Text(
                        text = macro.label,
                        style = TextStyle(fontSize = 12.sp, lineHeight = 16.sp, color = LifeFaint)
                    )
                }
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = "${lifeGram(macro.grams)} g",
                    style = TextStyle(
                        fontSize = 16.sp,
                        lineHeight = 22.sp,
                        fontWeight = FontWeight.Medium,
                        color = LifeInk,
                        fontFeatureSettings = "tnum"
                    )
                )
            }
        }
    }
}

/** 一条餐食记录：餐次 + 时间 + 热量 / 菜名 / AI 标签 + 宏量。 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun MealRow(entry: NutritionEntry) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 14.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Row(modifier = Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = formatMealType(entry.mealType),
                    style = TextStyle(
                        fontSize = 15.sp,
                        lineHeight = 20.sp,
                        fontWeight = FontWeight.Medium,
                        color = LifeInk
                    )
                )
                Spacer(modifier = Modifier.width(10.dp))
                Text(
                    text = lifeClock(entry.startTime.toEpochMilli()) ?: "--:--",
                    style = LifeMonoStyle.copy(fontSize = 12.sp, lineHeight = 16.sp)
                )
            }
            Spacer(modifier = Modifier.width(12.dp))
            entry.calories?.let { calories ->
                Text(
                    text = "${lifeCount(calories.toDouble())} kcal",
                    style = LifeValueStyle
                )
            }
        }

        Text(
            text = entry.title?.takeIf { it.isNotBlank() } ?: "未命名食物",
            style = TextStyle(fontSize = 14.sp, lineHeight = 21.sp, color = LifeMute)
        )

        val macroText = buildList {
            entry.protein?.let { add("蛋白 ${lifeGram(it.toDouble())}g") }
            entry.carbs?.let { add("碳水 ${lifeGram(it.toDouble())}g") }
            entry.fat?.let { add("脂肪 ${lifeGram(it.toDouble())}g") }
        }.joinToString(" · ")
        val aiLabel = when {
            entry.source == "ai_photo_label" -> "包装标签"
            entry.source.startsWith("ai_photo") -> "AI 照片估算"
            else -> null
        }
        if (macroText.isNotEmpty() || aiLabel != null) {
            FlowRow(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                if (aiLabel != null) {
                    AiBadge(label = aiLabel)
                }
                if (macroText.isNotEmpty()) {
                    Text(
                        text = macroText,
                        style = TextStyle(fontSize = 12.5.sp, lineHeight = 18.sp, color = LifeFaint)
                    )
                }
            }
        }
    }
}

/** AI 估算标签：22dp 高、沙金文字、40% 沙金描边。 */
@Composable
private fun AiBadge(label: String) {
    Row(
        modifier = Modifier
            .height(22.dp)
            .border(1.dp, LifeAiBorder, RoundedCornerShape(11.dp))
            .padding(horizontal = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = label,
            style = TextStyle(fontSize = 11.5.sp, lineHeight = 14.sp, color = LifeMacroLight)
        )
    }
}

/** 两列细线列表：行内左标签右值，底部细线。 */
@Composable
private fun MicroGrid(items: List<Pair<String, String>>) {
    Column {
        items.chunked(2).forEach { rowItems ->
            Row(modifier = Modifier.fillMaxWidth()) {
                MicroCell(item = rowItems[0], modifier = Modifier.weight(1f))
                Spacer(modifier = Modifier.width(24.dp))
                if (rowItems.size > 1) {
                    MicroCell(item = rowItems[1], modifier = Modifier.weight(1f))
                } else {
                    Spacer(modifier = Modifier.weight(1f))
                }
            }
        }
    }
}

@Composable
private fun MicroCell(
    item: Pair<String, String>,
    modifier: Modifier = Modifier
) {
    Column(modifier = modifier) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 11.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = item.first,
                style = TextStyle(fontSize = 14.sp, lineHeight = 20.sp, color = LifeMute)
            )
            Text(
                text = item.second,
                style = TextStyle(
                    fontSize = 14.5.sp,
                    lineHeight = 20.sp,
                    color = LifeInk,
                    fontFeatureSettings = "tnum"
                )
            )
        }
        LifeDivider(color = LifeTrackFaint)
    }
}

/** 餐次类型枚举名转中文显示。 */
private fun formatMealType(mealType: String?): String {
    if (mealType.isNullOrBlank()) return "饮食"
    return when (mealType.uppercase()) {
        "BREAKFAST" -> "早餐"
        "LUNCH" -> "午餐"
        "DINNER" -> "晚餐"
        "SNACK" -> "零食"
        else -> mealType.lowercase().replaceFirstChar { it.uppercase() }
    }
}
