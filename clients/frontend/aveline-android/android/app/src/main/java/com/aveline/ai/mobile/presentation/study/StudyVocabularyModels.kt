package com.aveline.ai.mobile.presentation.study

import kotlinx.serialization.Serializable

/**
 * 词汇模块共享数据模型。
 *
 * 从 StudyViewModel.kt 拆出：这些模型同时被 ViewModel、复习会话管理器、
 * 本地会话快照与词汇 Tab 使用，集中一处避免 ViewModel 继续膨胀。
 */

data class StudyRecord(
    val topic: String,
    val content: String,
    val time: String,
    /** 后端显式写入的分钟数；手写记录没有该字段时为 null。 */
    val minutes: Int? = null,
)

@Serializable
data class WordTranslation(
    val type: String,
    val translation: String,
    /** 仅由人工核对覆盖层标记；禁止根据数组第一项自动推断。 */
    val primary: Boolean = false,
    /** ECDICT 学科/语域标签，如“计”“医”；普通释义为空列表。 */
    val domains: List<String> = emptyList()
)

@Serializable
data class WordPhrase(
    val phrase: String,
    val translation: String
)

@Serializable
data class WordSentence(
    val sentence: String,
    val translation: String
)

@Serializable
data class DailyWord(
    val word: String,
    val translations: List<WordTranslation>,
    val extendedTranslations: List<WordTranslation> = emptyList(),
    val phrases: List<WordPhrase>?,
    val sentences: List<WordSentence>?,
    val us: String?,
    val uk: String?,
    val status: String,
    val dueTime: Long?
)

data class SessionStats(
    val active: Boolean,
    val duration: Int,
    val wordsReviewed: Int,
    val correctCount: Int,
    val accuracy: Double,
    val streak: Int
)
