package com.aveline.ai.mobile.presentation.study

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.domain.repository.StudyRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import javax.inject.Inject

/**
 * 学习模块 UI 状态
 *
 * 仅保留通用/概览/记录相关字段；词汇复习状态已拆分到 [VocabUiState]。
 *
 * @property isLoading 是否加载中
 * @property error 错误信息
 */
data class StudyUiState(
    val isLoading: Boolean = false,
    val error: String? = null,
    val successMessage: String? = null,
    val overviewTitle: String = "",
    val overviewSummary: String = "",
    val studyStreakDays: Int = 0,
    val reviewedToday: Int = 0,
    val todayStudyMinutes: Int = 0,
    val recordTopic: String = "英语",
    val recordContent: String = "",
    val recordDuration: Int = 45,
    val studyRecords: List<StudyRecord> = emptyList()
)

/**
 * 学习模块 ViewModel
 *
 * 词汇复习逻辑委托给 [StudyVocabReviewManager]，
 * 学习会话与记录逻辑委托给 [StudySessionManager]。
 * 番茄钟（专注）逻辑已拆分到 [StudyFocusViewModel]。
 */
@HiltViewModel
class StudyViewModel @Inject constructor(
    @ApplicationContext context: Context,
    private val studyRepository: StudyRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(StudyUiState())
    val uiState: StateFlow<StudyUiState> = _uiState.asStateFlow()

    // 词汇复习专用状态流（与通用 uiState 分离，便于独立观察）
    private val _vocabUiState = MutableStateFlow(VocabUiState())
    val vocabUiState: StateFlow<VocabUiState> = _vocabUiState.asStateFlow()

    /** 学习时长已落库事件：计划页与今日学习时长需要跟着刷新。 */
    private val _studyTimeEvents = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val studyTimeEvents: SharedFlow<Unit> = _studyTimeEvents.asSharedFlow()

    // 背单词前台计时（只统计前台可见时间）
    private val vocabTimerManager by lazy {
        StudyVocabTimerManager(
            scope = viewModelScope,
            studyRepository = studyRepository,
            onReported = { final ->
                if (final) {
                    sessionManager.refreshWorkspaceStudy()
                    _studyTimeEvents.tryEmit(Unit)
                }
            }
        )
    }

    /** 当前复习会话累计前台秒数（复习页顶部实时展示）。 */
    val vocabElapsedSeconds: StateFlow<Int> get() = vocabTimerManager.elapsedSeconds

    // 词汇复习会话管理器（懒加载，确保 viewModelScope 已就绪）
    private val vocabReviewManager by lazy {
        StudyVocabReviewManager(
            viewModelScope,
            _uiState,
            _vocabUiState,
            studyRepository,
            StudyVocabSessionStore(context),
            vocabTimerManager,
            onReviewProgressChanged = {
                // 一组背完：总览的待复习数、今日已背、词书进度都要跟着变
                loadReviewOverview()
                vocabInsightsManager.refresh()
            }
        )
    }

    // 词汇学习洞察（今日已背 / 词书进度 / 已学单词）
    private val vocabInsightsManager by lazy {
        StudyVocabInsightsManager(viewModelScope, _vocabUiState, studyRepository)
    }

    // 学习会话与记录管理器（懒加载，确保 viewModelScope 已就绪）
    private val sessionManager by lazy {
        StudySessionManager(viewModelScope, _uiState, studyRepository)
    }

    init {
        sessionManager.refreshWorkspaceStudy()
        // App 冷启动时优先恢复未完成的三轮强化队列，避免远端列表覆盖本地断点。
        if (!vocabReviewManager.restoreUnfinishedSession()) {
            loadLearnWords()
        }
        loadReviewOverview()
        loadMistakes()
        vocabInsightsManager.refresh()
    }

    /** 刷新工作区学习概览（委托给会话管理器） */
    fun refreshWorkspaceStudy() = sessionManager.refreshWorkspaceStudy()

    // ===== 词汇复习相关：委托给 StudyVocabReviewManager =====

    /** 加载待复习词汇（委托给词汇复习管理器，按当前 wordOrder 排序） */
    fun loadLearnWords() = vocabReviewManager.loadLearnWords(_vocabUiState.value.wordOrder)

    /** 开始背新单词会话（按已选分组数量从词书取未学过的新词） */
    fun startNewWords() = vocabReviewManager.startNewWordsSession()

    /** 设置每次背新词的分组数量 */
    fun setNewWordsBatchSize(batchSize: Int) = vocabReviewManager.setNewWordsBatchSize(batchSize)

    /** 设置每次复习的分组数量 */
    fun setReviewBatchSize(batchSize: Int) = vocabReviewManager.setReviewBatchSize(batchSize)

    /** 刷新今日已背 / 词书进度 / 已学单词 */
    fun loadVocabInsights() = vocabInsightsManager.refresh()

    /** 词典搜索 */
    fun searchDictionary(query: String) {
        val trimmed = query.trim()
        if (trimmed.isEmpty()) {
            _vocabUiState.update { it.copy(searchResults = emptyList(), isSearching = false) }
            return
        }
        viewModelScope.launch {
            _vocabUiState.update { it.copy(isSearching = true) }
            studyRepository.searchDictionary(trimmed).onSuccess { resp ->
                val results = mutableListOf<DictSearchResult>()
                // 后端可能返回精确匹配 {word, definition} 或模糊匹配 {matches: [...]}
                val matchType = resp["match_type"]?.let { (it as? JsonPrimitive)?.content }
                if (matchType == "exact") {
                    val word = resp["word"]?.let { (it as? JsonPrimitive)?.content }.orEmpty()
                    val def = resp["definition"] as? JsonArray
                    val translation = def?.firstOrNull()
                        ?.let { (it as? JsonObject)?.get("translation") as? JsonPrimitive }?.content
                        ?: ""
                    if (word.isNotEmpty()) {
                        results.add(DictSearchResult(word, translation))
                    }
                } else {
                    val matches = resp["matches"] as? JsonArray
                    matches?.forEach { m ->
                        val obj = m as? JsonObject ?: return@forEach
                        val word = obj["word"]?.let { (it as? JsonPrimitive)?.content }.orEmpty()
                        val def = obj["definition"] as? JsonArray
                        val translation = def?.firstOrNull()
                            ?.let { (it as? JsonObject)?.get("translation") as? JsonPrimitive }?.content
                            ?: ""
                        if (word.isNotEmpty()) {
                            results.add(DictSearchResult(word, translation))
                        }
                    }
                }
                _vocabUiState.update { it.copy(searchResults = results, isSearching = false) }
            }.onFailure { e ->
                _vocabUiState.update { it.copy(isSearching = false) }
                _uiState.update { it.copy(error = e.message ?: "搜索失败") }
            }
        }
    }

    /** 清空搜索结果 */
    fun clearSearch() {
        _vocabUiState.update { it.copy(searchResults = emptyList(), isSearching = false) }
    }

    /** 加载复习总览（今日待复习、连续天数、记忆曲线等） */
    fun loadReviewOverview() {
        viewModelScope.launch {
            studyRepository.getReviewOverview().onSuccess { resp ->
                val data = resp["data"]?.let { it as? JsonObject } ?: resp
                val curve = (data["memory_curve"] as? JsonArray)?.mapNotNull { p ->
                    val obj = p as? JsonObject ?: return@mapNotNull null
                    val day = (obj["day"] as? JsonPrimitive)?.content?.toIntOrNull() ?: 0
                    val retention = (obj["retention"] as? JsonPrimitive)?.content?.toFloatOrNull() ?: 0f
                    MemoryCurvePoint(day, retention)
                } ?: emptyList()
                _vocabUiState.update {
                    it.copy(
                        reviewOverview = ReviewOverview(
                            dueTodayCount = data.int("due_today_count") ?: 0,
                            streakDays = data.int("streak_days") ?: 0,
                            learnedWords = data.int("learned_words") ?: 0,
                            dueWords = data.int("due_words") ?: 0,
                            masteredWords = data.int("mastered_words") ?: 0,
                            newToday = data.int("new_today") ?: 0,
                            reviewToday = data.int("review_today") ?: 0,
                            memoryCurve = curve
                        )
                    )
                }
            }.onFailure { e ->
                _uiState.update { it.copy(error = e.message ?: "加载复习总览失败") }
            }
        }
    }

    /** 加载高错词列表 */
    fun loadMistakes() {
        viewModelScope.launch {
            studyRepository.getMistakes().onSuccess { resp ->
                val data = resp["data"] as? JsonArray
                val list = data?.mapNotNull { m ->
                    val obj = m as? JsonObject ?: return@mapNotNull null
                    val word = obj["word"]?.let { (it as? JsonPrimitive)?.content } ?: return@mapNotNull null
                    val errorCount = (obj["error_count"] as? JsonPrimitive)?.content?.toIntOrNull() ?: 0
                    val translations = obj["translations"] as? JsonArray
                    val translation = translations?.firstOrNull()
                        ?.let { (it as? JsonObject)?.get("translation") as? JsonPrimitive }?.content
                        ?: ""
                    MistakeWord(word, errorCount, translation)
                } ?: emptyList()
                _vocabUiState.update { it.copy(mistakes = list) }
            }.onFailure { e ->
                _uiState.update { it.copy(error = e.message ?: "加载错词失败") }
            }
        }
    }

    /** 切换词汇排序模式: sequential(顺序) / shuffle(乱序)，切换后重新加载 */
    fun toggleWordOrder() {
        val next = if (_vocabUiState.value.wordOrder == "sequential") "shuffle" else "sequential"
        _vocabUiState.update { it.copy(wordOrder = next) }
        vocabReviewManager.loadLearnWords(next)
    }

    /** 手动记录当天背了多少个单词 */
    fun addManualStudy(count: Int) {
        viewModelScope.launch {
            studyRepository.addManualStudy(count).onSuccess { resp ->
                val data = resp["data"]?.takeIf { it is JsonObject } as? JsonObject
                val dayTotal = (data?.get("day_total") as? JsonPrimitive)
                    ?.content?.toIntOrNull() ?: count
                _vocabUiState.update { it.copy(manualStudyToday = dayTotal) }
                _uiState.update {
                    it.copy(successMessage = "已记录 $count 个,今日累计 $dayTotal 个")
                }
            }.onFailure { e ->
                _uiState.update { it.copy(error = e.message ?: "记录失败") }
            }
        }
    }

    /** 加载今日已手动记录的单词总数(进入词汇 Tab 时调用) */
    fun loadManualStudyToday() {
        viewModelScope.launch {
            val today = java.text.SimpleDateFormat(
                "yyyy-MM-dd", java.util.Locale.getDefault()
            ).format(java.util.Date())
            studyRepository.getManualStudyStats(date = today).onSuccess { resp ->
                val data = resp["data"]?.takeIf { it is JsonObject } as? JsonObject
                val total = (data?.get("total") as? JsonPrimitive)
                    ?.content?.toIntOrNull() ?: 0
                _vocabUiState.update { it.copy(manualStudyToday = total) }
            }
        }
    }

    /** 加载词书列表与当前词书 */
    fun loadVocabBooks() {
        viewModelScope.launch {
            studyRepository.getVocabBookStats().onSuccess { resp ->
                val data = resp["data"]?.takeIf { it is JsonObject } as? JsonObject ?: return@onSuccess
                val books = (data["available_word_files"] as? kotlinx.serialization.json.JsonArray)
                    ?.mapNotNull { (it as? JsonPrimitive)?.content }
                    ?: emptyList()
                val current = (data["current_dictionary"] as? JsonPrimitive)?.content ?: ""
                _vocabUiState.update { it.copy(vocabBooks = books, currentBook = current) }
            }
        }
    }

    /** 加载当前词书内的单词列表 */
    fun loadBookWords(page: Int = 1, pageSize: Int = 60) {
        viewModelScope.launch {
            studyRepository.getBookWords(page, pageSize).onSuccess { resp ->
                val data = resp["data"]?.takeIf { it is JsonObject } as? JsonObject ?: return@onSuccess
                val total = (data["total"] as? JsonPrimitive)?.content?.toIntOrNull() ?: 0
                val words = (data["words"] as? kotlinx.serialization.json.JsonArray)
                    ?.mapNotNull { el ->
                        val obj = el as? JsonObject ?: return@mapNotNull null
                        val w = (obj["word"] as? JsonPrimitive)?.content ?: return@mapNotNull null
                        val translations = obj["translations"] as? JsonArray
                        val t = translations?.firstOrNull()
                            ?.let { (it as? JsonObject)?.get("translation") as? JsonPrimitive }?.content
                            ?: (obj["translation"] as? JsonPrimitive)?.content
                            ?: ""
                        BookWord(w, t)
                    } ?: emptyList()
                _vocabUiState.update { it.copy(bookWords = words, bookTotal = total) }
            }
        }
    }

    /** 切换当前词书 */
    fun switchVocabBook(filename: String) {
        viewModelScope.launch {
            studyRepository.switchVocabBook(filename).onSuccess {
                _vocabUiState.update { it.copy(currentBook = filename, bookWords = emptyList()) }
                loadVocabBooks()
                loadBookWords()
            }.onFailure { e ->
                _uiState.update { it.copy(error = e.message ?: "切换词书失败") }
            }
        }
    }

    /** 开始复习会话（委托给词汇复习管理器） */
    fun startReview() = vocabReviewManager.startReview()

    /** 学习页回到前台：背单词计时继续累加。 */
    fun onVocabSessionForeground() = vocabTimerManager.onForeground()

    /** App / 学习页进入后台：背单词计时暂停，后台时间不计入。 */
    fun onVocabSessionBackground() = vocabTimerManager.onBackground()

    override fun onCleared() {
        vocabTimerManager.clear()
        super.onCleared()
    }

    /** 提交复习评分（委托给词汇复习管理器） */
    fun submitReview(quality: Int) = vocabReviewManager.submitReview(quality)

    /** 结束复习会话（委托给词汇复习管理器） */
    fun finishSession() = vocabReviewManager.finishSession()

    /** 设置是否展示答案（委托给词汇复习管理器） */
    fun setShowAnswer(show: Boolean) = vocabReviewManager.setShowAnswer(show)

    /** 设置复习模式开关（委托给词汇复习管理器） */
    fun setIsReviewMode(isReview: Boolean) = vocabReviewManager.setIsReviewMode(isReview)

    /** 设置会话总结（委托给词汇复习管理器） */
    fun setSessionSummary(summary: Any?) = vocabReviewManager.setSessionSummary(summary)

    // ===== 学习记录与会话相关：委托给 StudySessionManager =====

    /** 写入学习记录（委托给会话管理器） */
    fun recordStudyProgress() = sessionManager.recordStudyProgress()

    /** 开始学习会话（委托给会话管理器） */
    fun startStudySession() = sessionManager.startStudySession()

    /** 结束学习会话（委托给会话管理器） */
    fun finishStudySession() = sessionManager.finishStudySession()

    fun setRecordTopic(value: String) {
        _uiState.update { it.copy(recordTopic = value) }
    }

    fun setRecordContent(value: String) {
        _uiState.update { it.copy(recordContent = value) }
    }

    fun setRecordDuration(value: String) {
        _uiState.update { it.copy(recordDuration = value.toIntOrNull() ?: 45) }
    }

    /**
     * 清除错误
     */
    fun clearError() {
        _uiState.update { it.copy(error = null, successMessage = null) }
    }
}
