package com.aveline.ai.mobile.presentation.study

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull

/**
 * 学习模块共享的 JSON 解析辅助函数
 *
 * 将原本散落在 StudyViewModel.kt 中的私有扩展函数集中管理，
 * 供 StudyViewModel、StudyVocabReviewManager、StudySessionManager 复用。
 *
 * 注意:所有读取函数都先判断字段是否为 [JsonPrimitive],
 * 避免后端返回 JsonObject/JsonArray 时调用 jsonPrimitive 抛 IllegalStateException 导致崩溃。
 */

/** 空数组兜底，避免可空 JsonArray 反复判空 */
internal fun JsonArray?.orEmptyArray(): JsonArray {
    return this ?: JsonArray(emptyList())
}

/** 读取字符串字段，缺失或非基本类型时返回空串 */
internal fun JsonObject.string(key: String): String {
    val element = this[key] ?: return ""
    if (element !is JsonPrimitive) return ""
    return element.contentOrNull.orEmpty()
}

/** 读取整数字段，缺失或非基本类型时返回 null */
internal fun JsonObject.int(key: String): Int? {
    val element = this[key] ?: return null
    if (element !is JsonPrimitive) return null
    return element.intOrNull
}

/** 读取长整数字段，缺失或非基本类型时返回 null */
internal fun JsonObject.long(key: String): Long? {
    val element = this[key] ?: return null
    if (element !is JsonPrimitive) return null
    return element.longOrNull
}

/** 读取布尔字段，缺失或非基本类型时返回 null */
internal fun JsonObject.boolean(key: String): Boolean? {
    val element = this[key] ?: return null
    if (element !is JsonPrimitive) return null
    return element.booleanOrNull
}

/** 读取浮点字段，缺失或非基本类型时返回 null */
internal fun JsonObject.double(key: String): Double? {
    val element = this[key] ?: return null
    if (element !is JsonPrimitive) return null
    return element.doubleOrNull
}

/**
 * 从 workspace study panel 响应解析今日学习分钟数。
 *
 * study_panel.today 是权威口径（含背单词前台计时）；workspace_snapshot.portrait
 * 是旧版快照路径，仅作兼容兜底。字段缺失时返回 0。
 */
internal fun parseTodayStudyMinutes(response: JsonObject): Int {
    val data = response["data"] as? JsonObject ?: response
    val studyToday = (data["study_panel"] as? JsonObject)
        ?.get("today") as? JsonObject
    val studyPortrait = ((data["workspace_snapshot"] as? JsonObject)
        ?.get("portrait") as? JsonObject)
        ?.get("study") as? JsonObject
    return studyToday?.int("total_minutes")
        ?: studyPortrait?.int("total_minutes")
        ?: 0
}
