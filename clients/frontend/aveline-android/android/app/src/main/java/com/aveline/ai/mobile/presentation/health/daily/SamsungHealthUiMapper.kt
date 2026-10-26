package com.aveline.ai.mobile.presentation.health.daily

import com.aveline.ai.mobile.data.samsung.SamsungHealthSnapshot

/**
 * 把三星健康快照合并进 [DailyDataUiState]。
 *
 * 抽成独立函数的原因：启动同步与 Life 页同步拿到的是同一种快照，
 * 两边都要走同一套"快照 → UI 字段"映射。以前映射逻辑写死在 ViewModel 里，
 * 启动同步读到的快照用完即弃，Life 页只能自己再读一遍 SDK（卡几秒的根因）。
 *
 * 合并语义：快照里为 null 的字段保留原值，不覆盖已有数据
 * （手表实时数据、AI 照片营养条目等其它来源的字段不能被清空）。
 */
fun SamsungHealthSnapshot.mergeInto(state: DailyDataUiState): DailyDataUiState = state.copy(
    // 步数优先用 Samsung Health 聚合值(与"今日活动"区块一致),
    // 聚合值为空时回退到手表实时值
    steps = stepsToday?.takeIf { it > 0 } ?: state.steps,
    heartRate = heartRate ?: state.heartRate,
    heartRateTimestamp = heartRateTimestamp?.toEpochMilli() ?: state.heartRateTimestamp,
    sleepMinutes = sleepMinutes ?: state.sleepMinutes,
    sleepStartTime = sleepStartTime?.toEpochMilli() ?: state.sleepStartTime,
    sleepEndTime = sleepEndTime?.toEpochMilli() ?: state.sleepEndTime,
    // 睡眠阶段时长
    sleepStageAwakeMinutes = sleepStageMinutes?.awake ?: state.sleepStageAwakeMinutes,
    sleepStageLightMinutes = sleepStageMinutes?.light ?: state.sleepStageLightMinutes,
    sleepStageDeepMinutes = sleepStageMinutes?.deep ?: state.sleepStageDeepMinutes,
    sleepStageRemMinutes = sleepStageMinutes?.rem ?: state.sleepStageRemMinutes,
    // 睡眠得分
    sleepScore = sleepScore ?: state.sleepScore,
    healthWeightKg = weightKg?.toDouble() ?: state.healthWeightKg,
    heightM = heightM?.toDouble() ?: state.heightM,
    bodyFatPercent = bodyFatPercent?.toDouble() ?: state.bodyFatPercent,
    skeletalMusclePercent = skeletalMusclePercent?.toDouble() ?: state.skeletalMusclePercent,
    // 身体成分扩展字段
    muscleMass = muscleMass?.toDouble() ?: state.muscleMass,
    bodyFatMass = bodyFatMass?.toDouble() ?: state.bodyFatMass,
    fatFreeMass = fatFreeMass?.toDouble() ?: state.fatFreeMass,
    skeletalMuscleMass = skeletalMuscleMass?.toDouble() ?: state.skeletalMuscleMass,
    totalBodyWater = totalBodyWater?.toDouble() ?: state.totalBodyWater,
    bloodPressureSystolic = systolic?.toDouble() ?: state.bloodPressureSystolic,
    bloodPressureDiastolic = diastolic?.toDouble() ?: state.bloodPressureDiastolic,
    bodyTemperature = bodyTemperature?.toDouble() ?: state.bodyTemperature,
    bloodGlucose = bloodGlucose?.toDouble() ?: state.bloodGlucose,
    // 扩展字段
    skinTemperature = skinTemperature?.toDouble() ?: state.skinTemperature,
    bloodOxygen = bloodOxygen?.toDouble() ?: state.bloodOxygen,
    floorsClimbed = floorsClimbed?.toDouble() ?: state.floorsClimbed,
    waterIntakeMl = waterIntakeMl?.toDouble() ?: state.waterIntakeMl,
    nutritionCalories = nutritionCalories?.toDouble() ?: state.nutritionCalories,
    nutritionProtein = nutritionProtein?.toDouble() ?: state.nutritionProtein,
    nutritionCarbs = nutritionCarbs?.toDouble() ?: state.nutritionCarbs,
    nutritionFat = nutritionFat?.toDouble() ?: state.nutritionFat,
    nutritionSaturatedFat = nutritionSaturatedFat?.toDouble() ?: state.nutritionSaturatedFat,
    nutritionTransFat = nutritionTransFat?.toDouble() ?: state.nutritionTransFat,
    nutritionDietaryFiber = nutritionDietaryFiber?.toDouble() ?: state.nutritionDietaryFiber,
    nutritionSugar = nutritionSugar?.toDouble() ?: state.nutritionSugar,
    nutritionCholesterol = nutritionCholesterol?.toDouble() ?: state.nutritionCholesterol,
    nutritionSodium = nutritionSodium?.toDouble() ?: state.nutritionSodium,
    nutritionPotassium = nutritionPotassium?.toDouble() ?: state.nutritionPotassium,
    nutritionVitaminA = nutritionVitaminA?.toDouble() ?: state.nutritionVitaminA,
    nutritionVitaminC = nutritionVitaminC?.toDouble() ?: state.nutritionVitaminC,
    nutritionCalcium = nutritionCalcium?.toDouble() ?: state.nutritionCalcium,
    nutritionIron = nutritionIron?.toDouble() ?: state.nutritionIron,
    exerciseSessions = exerciseSessions,
    nutritionEntries = nutritionEntries + state.nutritionEntries.filter {
        entry -> entry.source.startsWith("ai_photo")
    },
    waterIntakeEntries = waterIntakeEntries,
    sleepApneaSign = sleepApneaSign ?: state.sleepApneaSign,
    irregularHeartRhythmStatus = irregularHeartRhythmStatus ?: state.irregularHeartRhythmStatus,
    energyScore = energyScore?.toDouble() ?: state.energyScore,
    stepsToday = stepsToday ?: state.stepsToday,
    activeCaloriesBurned = activeCaloriesBurned?.toDouble() ?: state.activeCaloriesBurned,
    totalCaloriesBurned = totalCaloriesBurned?.toDouble() ?: state.totalCaloriesBurned,
    activeTimeMinutes = activeTimeMinutes ?: state.activeTimeMinutes,
    totalDistanceKm = totalDistanceKm?.toDouble() ?: state.totalDistanceKm,
    sleepGoalBedTime = sleepGoalBedTime?.toString() ?: state.sleepGoalBedTime,
    sleepGoalWakeTime = sleepGoalWakeTime?.toString() ?: state.sleepGoalWakeTime,
    stepsGoal = stepsGoal ?: state.stepsGoal,
    activeCaloriesGoal = activeCaloriesGoal ?: state.activeCaloriesGoal,
    activeTimeGoalMinutes = activeTimeGoalMinutes ?: state.activeTimeGoalMinutes,
    waterIntakeGoalMl = waterIntakeGoalMl?.toDouble() ?: state.waterIntakeGoalMl,
    nutritionGoalCalories = nutritionGoalCalories?.toDouble() ?: state.nutritionGoalCalories
)
