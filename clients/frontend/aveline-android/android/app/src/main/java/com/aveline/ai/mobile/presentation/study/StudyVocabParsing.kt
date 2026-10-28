package com.aveline.ai.mobile.presentation.study

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.util.LinkedHashMap

/**
 * 复习结果按单词去重：同一单词多次提交（如 Again 重排）只保留最后一次结果，
 * 并保持首次出现顺序。用于结算页「会/不会」清单与正确率统计，避免重复计数。
 */
internal fun dedupeResults(list: List<ReviewResultItem>): List<ReviewResultItem> {
    val map = LinkedHashMap<String, ReviewResultItem>()
    for (item in list) map[item.word.lowercase()] = item
    return map.values.toList()
}

/** 解析普通释义或扩展释义，缺少新字段时兼容旧词书。 */
private fun JsonObject.parseTranslations(key: String): List<WordTranslation> {
    return this[key]
        ?.jsonArray
        ?.map { element ->
            val translation = element.jsonObject
            WordTranslation(
                type = translation.string("type"),
                translation = translation.string("translation"),
                primary = translation.boolean("primary") ?: false,
                domains = translation["domains"]
                    ?.jsonArray
                    ?.mapNotNull { it.jsonPrimitive.contentOrNull }
                    .orEmpty()
            )
        }
        .orEmpty()
}

/**
 * 词汇复习会话管理器
 *
 * 从 StudyViewModel 中提取的词汇复习相关逻辑，负责：
 * - 加载待复习的词汇列表（Learn Words）
 * - 开始/提交/结束一次复习会话
 * - 维护复习卡片索引、是否展示答案、会话统计等 UI 状态
 *
 * 词汇复习专用状态写入独立的 [VocabUiState] 流（由 ViewModel 持有并暴露），
 * 通用加载/错误状态仍写入共享的 [StudyUiState] 流。
 *
 * @property scope 协程作用域，通常为 ViewModel 的 viewModelScope
 * @property uiState 通用可变状态流（仅用于 isLoading / error 等共享字段）
 * @property vocabState 词汇复习专用可变状态流
 * @property studyRepository 学习仓库，负责远端数据访问
 */

/** 解析后端返回的词汇列表为 DailyWord 列表（复用于复习词和新词） */
internal fun parseDailyWords(response: JsonObject): List<DailyWord> {
    return response["data"]?.jsonArray.orEmptyArray().map { item ->
        val obj = item.jsonObject
        val translations = obj.parseTranslations("translations")
        val extendedTranslations = obj.parseTranslations("extended_translations")
        val phrases = obj["phrases"]
            ?.jsonArray
            ?.map { p ->
                val pObj = p.jsonObject
                WordPhrase(
                    phrase = pObj.string("phrase"),
                    translation = pObj.string("translation")
                )
            }
        val sentences = obj["sentences"]
            ?.jsonArray
            ?.map { s ->
                val sObj = s.jsonObject
                WordSentence(
                    sentence = sObj.string("sentence"),
                    translation = sObj.string("translation")
                )
            }
        DailyWord(
            word = obj.string("word"),
            translations = translations,
            extendedTranslations = extendedTranslations,
            phrases = phrases,
            sentences = sentences,
            us = obj["us"]?.jsonPrimitive?.contentOrNull,
            uk = obj["uk"]?.jsonPrimitive?.contentOrNull,
            status = obj.string("status"),
            dueTime = obj.long("due_time")
        )
    }
}
