package com.aveline.ai.mobile.presentation.study

import com.aveline.ai.mobile.domain.repository.StudyRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray

/**
 * 词汇学习洞察加载器。
 *
 * 负责三块只读数据，写入 [VocabUiState]：
 * - 今日已背单词明细（新学/复习、评分、时间）
 * - 当前词书进度（已学/总数/掌握/待复习）
 * - 已学单词预览列表（词书进度卡里展示最近学过的词）
 *
 * 这些请求失败时不打扰用户：首页仍有本地统计兜底，下次进入词汇 Tab 会重试。
 */
class StudyVocabInsightsManager(
    private val scope: CoroutineScope,
    private val vocabState: MutableStateFlow<VocabUiState>,
    private val studyRepository: StudyRepository
) {
    /** 进入词汇 Tab / 会话结束后刷新全部洞察数据。 */
    fun refresh() {
        loadTodayWords()
        loadBookProgress()
        loadLearnedWords()
    }

    fun loadTodayWords() {
        scope.launch {
            studyRepository.getTodayWords().onSuccess { resp ->
                val data = resp.payload()
                val words = data["words"]?.jsonArray.orEmptyArray().map { item ->
                    val obj = item as? JsonObject ?: return@map null
                    TodayVocabWord(
                        word = obj.string("word"),
                        translation = obj.string("translation"),
                        status = obj.string("status"),
                        reviews = obj.int("reviews") ?: 1,
                        lastQuality = obj.int("last_quality") ?: 0,
                        lastReviewAt = obj.string("last_review_at")
                    )
                }.filterNotNull()
                val summary = TodayVocabSummary(
                    date = data.string("date"),
                    total = data.int("total") ?: words.size,
                    newWords = data.int("new_words") ?: 0,
                    reviewWords = data.int("review_words") ?: 0,
                    reviewEvents = data.int("review_events") ?: 0,
                    againWords = data.int("again_words") ?: 0,
                    knownWords = data.int("known_words") ?: 0,
                    words = words
                )
                vocabState.update { it.copy(todayVocab = summary) }
            }
        }
    }

    fun loadBookProgress() {
        scope.launch {
            studyRepository.getBookProgress().onSuccess { resp ->
                val data = resp.payload()
                val progress = VocabBookProgress(
                    currentBook = data.string("current_dictionary"),
                    totalWords = data.int("total_words") ?: 0,
                    learnedWords = data.int("learned_words") ?: 0,
                    remainingWords = data.int("remaining_words") ?: 0,
                    masteredWords = data.int("mastered_words") ?: 0,
                    learningWords = data.int("learning_words") ?: 0,
                    dueWords = data.int("due_words") ?: 0,
                    progressPercent = (data.double("progress_percent") ?: 0.0).toFloat(),
                    todayNew = data.int("today_new") ?: 0,
                    todayReview = data.int("today_review") ?: 0
                )
                vocabState.update { state ->
                    state.copy(
                        bookProgress = progress,
                        currentBook = progress.currentBook.ifBlank { state.currentBook }
                    )
                }
            }
        }
    }

    /** 只取最近一页用于预览；完整列表留给后续「已学单词」页复用同一接口。 */
    fun loadLearnedWords() {
        scope.launch {
            studyRepository.getLearnedWords(page = 1, pageSize = 10, status = "all", scope = "book")
                .onSuccess { resp ->
                    val data = resp.payload()
                    val words = data["words"]?.jsonArray.orEmptyArray().map { item ->
                        val obj = item as? JsonObject ?: return@map null
                        LearnedWordItem(
                            word = obj.string("word"),
                            translation = obj.string("translation"),
                            status = obj.string("status"),
                            intervalDays = obj.int("interval_days") ?: 0,
                            lastReviewAt = obj.string("last_review_at")
                        )
                    }.filterNotNull()
                    vocabState.update {
                        it.copy(
                            learnedWords = words,
                            learnedWordsTotal = data.int("total") ?: words.size
                        )
                    }
                }
        }
    }

    private fun JsonObject.payload(): JsonObject =
        (this["data"] as? JsonObject) ?: this
}
