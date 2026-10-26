package com.aveline.ai.mobile.presentation.health.daily

import com.aveline.ai.mobile.data.samsung.NutritionEntry
import com.aveline.ai.mobile.domain.repository.HealthRepository
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.time.Instant

/**
 * 后端 daily 接口的解析结果。
 *
 * 只装"这一轮解析出来的字段"，设备上下文与健康指标由各自的来源负责，
 * 不在这里混进来（避免 null 覆盖掉别处填好的值）。
 */
data class DailyPortraitData(
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
    val recentFiles: List<DailyRecentFile> = emptyList()
)

/**
 * 解析 `GET /daily/portrait/today` 与 `GET /daily/recent` 的响应。
 *
 * 抽出来的原因：这些字段的解析逻辑占了 ViewModel 一大块，与"同步三星健康"无关，
 * 放在 ViewModel 里会让文件超限，也让"读后端"和"读 SDK"两件事缠在一起。
 */
fun parseDailyPortrait(portrait: JsonObject, recent: JsonObject): DailyPortraitData {
    val portraitData = portrait["portrait"]?.jsonObject ?: JsonObject(emptyMap())
    val schedule = portraitData["schedule"]?.jsonObject
    val drink = portraitData["drink"]?.jsonObject
    val study = portraitData["study"]?.jsonObject
    val mode = portraitData["mode"]?.jsonObject
    val bodyMetrics = portraitData["body_metrics"]?.jsonObject

    val sessions = study?.get("sessions")?.jsonArray.orEmptyArray().map { item ->
        val obj = item.jsonObject
        DailyStudySession(
            topic = obj.string("topic"),
            content = obj.string("content"),
            time = obj.string("time")
        )
    }
    val meals = portraitData["meals"]?.jsonArray.orEmptyArray().map { item ->
        val obj = item.jsonObject
        DailyMeal(
            type = obj.string("type"),
            content = obj.string("content"),
            time = obj.string("time")
        )
    }
    val files = recent["items"]?.jsonArray.orEmptyArray().map { item ->
        val obj = item.jsonObject
        DailyRecentFile(
            path = obj.string("path"),
            name = obj.string("name"),
            size = obj.int("size"),
            mtime = obj.int("mtime"),
            ext = obj.string("ext").ifBlank { null }
        )
    }

    return DailyPortraitData(
        portraitDate = portrait.string("date"),
        wakeup = schedule?.string("wakeup")?.ifBlank { null },
        sleep = schedule?.string("sleep")?.ifBlank { null },
        drinkTotalMl = drink?.int("total_ml") ?: 0,
        drinkCount = drink?.int("count") ?: 0,
        studyTotalMinutes = study?.int("total_minutes") ?: 0,
        studyCount = study?.int("count") ?: 0,
        studySessions = sessions,
        meals = meals,
        reducedModeActive = mode?.bool("reduced_mode_active") ?: false,
        reducedModeReason = mode?.string("reduced_mode_reason") ?: "",
        reducedModeExpectedEndTs = mode?.long("reduced_mode_expected_end_ts"),
        weightKg = bodyMetrics?.double("weight_kg"),
        recentFiles = files
    )
}

/**
 * 拉取"AI 拍照"识别出来的营养条目。
 *
 * 这些条目来自后端，与三星健康的饮食记录是两类来源，合并时不能互相覆盖。
 */
suspend fun loadAiNutritionEntries(
    repository: HealthRepository,
    date: String? = null
): List<NutritionEntry>? {
    val response = repository.getDailyNutrition(date).getOrNull() ?: return null
    val entries = response["data"]?.jsonObject?.get("nutrition_entries")?.jsonArray
        ?: return emptyList()
    return entries.mapNotNull { item ->
        val entry = runCatching { item.jsonObject }.getOrNull() ?: return@mapNotNull null
        val source = entry.string("source")
        if (!source.startsWith("ai_photo")) return@mapNotNull null
        val startTime = runCatching { Instant.parse(entry.string("time")) }.getOrNull()
            ?: return@mapNotNull null
        NutritionEntry(
            title = entry.string("title").ifBlank { null },
            mealType = entry.string("meal_type").ifBlank { null },
            calories = entry.double("calories")?.toFloat(),
            protein = entry.double("protein")?.toFloat(),
            carbs = entry.double("carbs")?.toFloat(),
            fat = entry.double("fat")?.toFloat(),
            startTime = startTime,
            saturatedFat = entry.double("saturated_fat")?.toFloat(),
            transFat = entry.double("trans_fat")?.toFloat(),
            monosaturatedFat = entry.double("monosaturated_fat")?.toFloat(),
            polysaturatedFat = entry.double("polysaturated_fat")?.toFloat(),
            dietaryFiber = entry.double("dietary_fiber")?.toFloat(),
            sugar = entry.double("sugar")?.toFloat(),
            cholesterol = entry.double("cholesterol")?.toFloat(),
            sodium = entry.double("sodium")?.toFloat(),
            potassium = entry.double("potassium")?.toFloat(),
            vitaminA = entry.double("vitamin_a")?.toFloat(),
            vitaminC = entry.double("vitamin_c")?.toFloat(),
            calcium = entry.double("calcium")?.toFloat(),
            iron = entry.double("iron")?.toFloat(),
            source = source,
            portion = entry.string("portion").ifBlank { null },
            estimateConfidence = entry.string("estimate_confidence").ifBlank { null }
        )
    }
}

internal fun JsonObject.string(key: String): String {
    return this[key]?.jsonPrimitive?.contentOrNull.orEmpty()
}

internal fun JsonObject.int(key: String): Int? {
    return this[key]?.jsonPrimitive?.intOrNull
}

internal fun JsonObject.long(key: String): Long? {
    return this[key]?.jsonPrimitive?.contentOrNull?.toLongOrNull()
}

internal fun JsonObject.double(key: String): Double? {
    return this[key]?.jsonPrimitive?.doubleOrNull
}

internal fun JsonObject.bool(key: String): Boolean? {
    return this[key]?.jsonPrimitive?.booleanOrNull
}

internal fun JsonArray?.orEmptyArray(): JsonArray {
    return this ?: JsonArray(emptyList())
}
