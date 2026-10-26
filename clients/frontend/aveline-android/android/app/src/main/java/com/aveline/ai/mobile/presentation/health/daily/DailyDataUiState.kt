package com.aveline.ai.mobile.presentation.health.daily

import com.aveline.ai.mobile.data.samsung.ExerciseSnapshot
import com.aveline.ai.mobile.data.samsung.NutritionEntry
import com.aveline.ai.mobile.data.samsung.WaterIntakeEntry
import com.aveline.ai.mobile.domain.models.BatteryStatus
import com.aveline.ai.mobile.domain.models.NetworkType

enum class DailyTab {
    PORTRAIT,
    SCHEDULE,
    FILES,
}

data class DailyRecentFile(
    val path: String,
    val name: String,
    val size: Int?,
    val mtime: Int?,
    val ext: String?,
)

data class DailyStudySession(
    val topic: String,
    val content: String,
    val time: String,
)

data class DailyMeal(
    val type: String,
    val content: String,
    val time: String,
)

data class DailyDataUiState(
    val activeTab: DailyTab = DailyTab.PORTRAIT,
    val isLoading: Boolean = false,
    val error: String? = null,
    val message: String? = null,
    val lastRefreshTime: Long = 0L,
    val portraitDate: String = "",
    val wakeup: String? = null,
    val sleep: String? = null,
    val drinkTotalMl: Int = 0,
    val drinkCount: Int = 0,
    val studyTotalMinutes: Int = 0,
    val studyCount: Int = 0,
    val studySessions: List<DailyStudySession> = emptyList(),
    val meals: List<DailyMeal> = emptyList(),
    val reducedModeActive: Boolean = false,
    val reducedModeReason: String = "",
    val reducedModeExpectedEndTs: Long? = null,
    val weightKg: Double? = null,
    val recentFiles: List<DailyRecentFile> = emptyList(),
    // 健康数据 (由 Samsung Health + 手表实时数据填充)
    val steps: Long? = null,
    val heartRate: Int? = null,
    val heartRateTimestamp: Long? = null,
    val healthWeightKg: Double? = null,
    val heightM: Double? = null,
    val bodyFatPercent: Double? = null,
    val skeletalMusclePercent: Double? = null,
    // 身体成分扩展字段(kg)
    val muscleMass: Double? = null,
    val bodyFatMass: Double? = null,
    val fatFreeMass: Double? = null,
    val skeletalMuscleMass: Double? = null,
    val totalBodyWater: Double? = null,
    val sleepMinutes: Long? = null,
    val sleepStartTime: Long? = null,
    val sleepEndTime: Long? = null,
    // 睡眠阶段时长(分钟), null 表示该阶段无记录
    val sleepStageAwakeMinutes: Long? = null,
    val sleepStageLightMinutes: Long? = null,
    val sleepStageDeepMinutes: Long? = null,
    val sleepStageRemMinutes: Long? = null,
    // 睡眠得分 (0-100)
    val sleepScore: Int? = null,
    val bloodPressureSystolic: Double? = null,
    val bloodPressureDiastolic: Double? = null,
    val bodyTemperature: Double? = null,
    val bloodGlucose: Double? = null,
    // Samsung Health 扩展数据
    val skinTemperature: Double? = null,
    val bloodOxygen: Double? = null,
    val floorsClimbed: Double? = null,
    val waterIntakeMl: Double? = null,
    val nutritionCalories: Double? = null,
    val nutritionProtein: Double? = null,
    val nutritionCarbs: Double? = null,
    val nutritionFat: Double? = null,
    val nutritionSaturatedFat: Double? = null,
    val nutritionTransFat: Double? = null,
    val nutritionDietaryFiber: Double? = null,
    val nutritionSugar: Double? = null,
    val nutritionCholesterol: Double? = null,
    val nutritionSodium: Double? = null,
    val nutritionPotassium: Double? = null,
    val nutritionVitaminA: Double? = null,
    val nutritionVitaminC: Double? = null,
    val nutritionCalcium: Double? = null,
    val nutritionIron: Double? = null,
    val exerciseSessions: List<ExerciseSnapshot> = emptyList(),
    // 今日逐条饮食记录(来自 Samsung Health 营养数据: 食物名/餐次/热量)
    val nutritionEntries: List<NutritionEntry> = emptyList(),
    // 今日逐条饮水记录(来自 Samsung Health: 时间+量)
    val waterIntakeEntries: List<WaterIntakeEntry> = emptyList(),
    val sleepApneaSign: String? = null,
    val irregularHeartRhythmStatus: String? = null,
    val energyScore: Double? = null,
    val stepsToday: Long? = null,
    val activeCaloriesBurned: Double? = null,
    val totalCaloriesBurned: Double? = null,
    val activeTimeMinutes: Long? = null,
    val totalDistanceKm: Double? = null,
    val sleepGoalBedTime: String? = null,
    val sleepGoalWakeTime: String? = null,
    val stepsGoal: Int? = null,
    val activeCaloriesGoal: Int? = null,
    val activeTimeGoalMinutes: Long? = null,
    val waterIntakeGoalMl: Double? = null,
    val nutritionGoalCalories: Double? = null,
    // 设备上下文 (电池/网络/亮度/音量) - 来自 ContextRepository, 不需要特殊权限
    val batteryLevel: Int? = null,
    val isCharging: Boolean = false,
    val batteryStatus: BatteryStatus = BatteryStatus.UNKNOWN,
    val networkType: NetworkType = NetworkType.UNKNOWN,
    val screenBrightness: Int? = null,
    val volumeLevel: Int? = null
)
