package com.aveline.ai.mobile.presentation.study

import com.aveline.ai.mobile.domain.repository.StudyRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.time.LocalDate
import java.util.LinkedHashMap

/**
 * 复习结果按单词去重：同一单词多次提交（如 Again 重排）只保留最后一次结果，
 * 并保持首次出现顺序。用于结算页「会/不会」清单与正确率统计，避免重复计数。
 */
private fun dedupeResults(list: List<ReviewResultItem>): List<ReviewResultItem> {
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
class StudyVocabReviewManager(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<StudyUiState>,
    private val vocabState: MutableStateFlow<VocabUiState>,
    private val studyRepository: StudyRepository,
    private val sessionStore: StudyVocabSessionStore? = null,
    /** 前台计时器：进入复习即开始计时，切后台/离开页面暂停。 */
    private val timerManager: StudyVocabTimerManager? = null,
    /** 一组复习结束后通知上层刷新复习总览 / 今日已背等只读数据。 */
    private val onReviewProgressChanged: () -> Unit = {}
) {
    private var pendingReviewSyncJob: Job? = null

    /**
     * 冷启动恢复未完成会话，但不自动打开全屏复习界面。
     * 用户再次点击对应入口后，由 startReview/startNewWordsSession 从断点继续。
     */
    fun restoreUnfinishedSession(): Boolean {
        // 旧版本存过 30 这类已下线的档位，恢复时丢弃，避免分段选择没有选中项。
        sessionStore?.getNewWordsBatchSize()
            ?.takeIf { it in NEW_WORDS_BATCH_SIZE_OPTIONS }
            ?.let { batchSize -> vocabState.update { it.copy(newWordsBatchSize = batchSize) } }
        sessionStore?.getReviewBatchSize()
            ?.takeIf { it in REVIEW_BATCH_SIZE_OPTIONS }
            ?.let { batchSize -> vocabState.update { it.copy(reviewBatchSize = batchSize) } }
        val snapshot = sessionStore?.restore() ?: return false
        vocabState.update {
            it.copy(
                learnWords = snapshot.learnWords,
                isReviewMode = false,
                isNewWordsMode = snapshot.isNewWordsMode,
                sessionDate = snapshot.date,
                sessionId = snapshot.sessionId,
                sessionElapsedSeconds = snapshot.elapsedSeconds,
                currentCardIndex = snapshot.currentCardIndex,
                showAnswer = false,
                redoCounts = snapshot.redoCounts,
                reviewResults = snapshot.reviewResults,
                sessionSummary = null
            )
        }
        return true
    }

    private fun persistUnfinishedSession() {
        val elapsed = timerManager?.currentSeconds() ?: vocabState.value.sessionElapsedSeconds
        sessionStore?.save(vocabState.value, elapsedSeconds = elapsed)
    }

    /** 进入复习界面时启动（或续上）前台计时。 */
    private fun startTimer(state: VocabUiState) {
        // 旧版快照没有 sessionId：补一个，避免续背时整段会话不计时。
        val sessionId = state.sessionId.ifBlank { newSessionId() }
        if (sessionId != state.sessionId) {
            vocabState.update { it.copy(sessionId = sessionId) }
        }
        timerManager?.startSession(
            sessionId = sessionId,
            mode = if (state.isNewWordsMode) "new_words" else "review",
            initialSeconds = state.sessionElapsedSeconds
        )
    }

    private fun newSessionId(): String =
        java.util.UUID.randomUUID().toString().replace("-", "").take(16)

    fun setNewWordsBatchSize(batchSize: Int) {
        if (batchSize !in NEW_WORDS_BATCH_SIZE_OPTIONS) return
        sessionStore?.saveNewWordsBatchSize(batchSize)
        vocabState.update { it.copy(newWordsBatchSize = batchSize) }
    }

    fun setReviewBatchSize(batchSize: Int) {
        if (batchSize !in REVIEW_BATCH_SIZE_OPTIONS) return
        sessionStore?.saveReviewBatchSize(batchSize)
        vocabState.update { it.copy(reviewBatchSize = batchSize) }
    }

    /** 设备本地时区的日期键（yyyy-MM-dd），与后端业务日期口径一致。 */
    private fun todayKey(): String = LocalDate.now().toString()

    /**
     * 本地是否压着一条没走完的队列（复习或背新词）。
     *
     * 退出全屏复习（返回键 / 切 Tab）不等于结束会话：队列里还压着 Again
     * 重排到队尾的词。跨天的残留队列（sessionDate 不是今天）不算未完成，
     * 避免昨天没背完的列表把今天的刷新锁死。
     */
    private fun hasPendingQueue(state: VocabUiState): Boolean =
        state.sessionDate.isNotEmpty() &&
            state.sessionDate == todayKey() &&
            state.learnWords.isNotEmpty() &&
            state.currentCardIndex < state.learnWords.size &&
            state.sessionSummary == null &&
            state.reviewResults.isNotEmpty()

    /**
     * 加载待学习的词汇列表（含翻译、短语、例句、发音等完整信息）
     *
     * 拉取成功后写入 [VocabUiState.learnWords]；失败时写入错误信息。
     *
     * 注意：本地还有未走完的队列时直接返回，不用远端列表覆盖。
     * 切到背单词 Tab 会调到这里，而远端当天批次只含「还没评分过」的词——
     * 覆盖一次就把 Again 重排到队尾的错词全丢了，用户中途退出等于跳过所有
     * 不会的词（后端按设计不重推今天已评分的词，当天再也推不到）。
     */
    fun loadLearnWords(order: String = "sequential") {
        scope.launch {
            if (hasPendingQueue(vocabState.value)) {
                return@launch
            }
            uiState.update { it.copy(isLoading = true, error = null) }
            studyRepository.getDailyVocabulary(0, order).onSuccess { response ->
                val words = parseDailyWords(response)
                uiState.update { it.copy(isLoading = false) }
                val current = vocabState.value
                // 上一组结算时发起的复习列表刷新，不能覆盖刚打开的新词组。
                if (current.isNewWordsMode && current.isReviewMode) return@onSuccess
                vocabState.update { it.copy(learnWords = words) }
            }.onFailure { error ->
                uiState.update {
                    it.copy(
                        isLoading = false,
                        error = error.message ?: "加载 Learn Words 失败"
                    )
                }
            }
        }
    }

    /**
     * 加载从未学过的新词列表（从当前词书取不在 progress 里的词）。
     *
     * 拉取成功后写入 [VocabUiState.learnWords] 并标记 [VocabUiState.isNewWordsMode]。
     */
    fun loadNewWords(
        count: Int = vocabState.value.newWordsBatchSize,
        order: String = "sequential"
    ) {
        scope.launch {
            uiState.update { it.copy(isLoading = true, error = null) }
            studyRepository.getNewWords(count, order).onSuccess { response ->
                val words = parseDailyWords(response)
                uiState.update { it.copy(isLoading = false) }
                vocabState.update { it.copy(learnWords = words, isNewWordsMode = true) }
            }.onFailure { error ->
                uiState.update {
                    it.copy(
                        isLoading = false,
                        error = error.message ?: "加载新词失败"
                    )
                }
            }
        }
    }

    /** 解析后端返回的词汇列表为 DailyWord 列表（复用于复习词和新词） */
    private fun parseDailyWords(response: JsonObject): List<DailyWord> {
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

    /**
     * 开始一次词汇复习会话。
     *
     * 与背新词一致按组领取：每次只拉 [VocabUiState.reviewBatchSize] 个待复习词，
     * 完成一组后再领下一组。后端当天队列会过滤掉已评分的词，所以无需游标。
     * 中途退出（本地队列未走完）仍从断点续背，不重新拉取。
     */
    fun startReview() {
        scope.launch {
            // 续背：内存里还有未完成的复习会话（非新词模式、有卡片、未背完、至少提交过一次）
            // 则从断点 currentCardIndex 继续，不重置索引、不重新拉取、不调后端开新会话。
            // 解决「中途退出再进从头重背」的体感问题。
            val current = vocabState.value
            val hasUnfinished = hasPendingQueue(current) && !current.isNewWordsMode

            if (hasUnfinished) {
                vocabState.update {
                    it.copy(
                        isReviewMode = true,
                        showAnswer = false
                    )
                }
                startTimer(vocabState.value)
                return@launch
            }

            // 正常开新会话：先领一组词，确保进入复习界面时就是本组的队列
            uiState.update { it.copy(isLoading = true, error = null) }
            val batchResult = studyRepository.getDailyReviewBatch(
                current.reviewBatchSize,
                _currentOrder()
            )
            val words = batchResult.getOrNull()?.let { parseDailyWords(it) }
            if (words == null) {
                uiState.update {
                    it.copy(
                        isLoading = false,
                        error = batchResult.exceptionOrNull()?.message ?: "加载复习词失败"
                    )
                }
                return@launch
            }
            if (words.isEmpty()) {
                uiState.update {
                    it.copy(isLoading = false, successMessage = "今天的复习已经全部完成")
                }
                vocabState.update {
                    it.copy(
                        isReviewMode = false,
                        sessionDate = "",
                        learnWords = emptyList()
                    )
                }
                onReviewProgressChanged()
                return@launch
            }

            studyRepository.startReviewSession().onSuccess {
                sessionStore?.clear()
                uiState.update { it.copy(isLoading = false) }
                vocabState.update {
                    it.copy(
                        learnWords = words,
                        isReviewMode = true,
                        isNewWordsMode = false,
                        sessionDate = todayKey(),
                        sessionId = newSessionId(),
                        sessionElapsedSeconds = 0,
                        currentCardIndex = 0,
                        showAnswer = false,
                        sessionSummary = null,
                        sessionStats = null,
                        reviewResults = emptyList(),
                        redoCounts = emptyMap()
                    )
                }
                startTimer(vocabState.value)
            }.onFailure { error ->
                uiState.update {
                    it.copy(isLoading = false, error = error.message ?: "开始复习失败")
                }
            }
        }
    }

    /**
     * 开始背新单词会话。
     *
     * 先加载新词，然后进入复习模式（复用翻卡 UI）。
     * 新词提交评分时 [submitReview] 会自动通过 FSRS 初始化进度。
     */
    fun startNewWordsSession(count: Int = vocabState.value.newWordsBatchSize) {
        scope.launch {
            val current = vocabState.value
            if (hasPendingQueue(current) && current.isNewWordsMode) {
                vocabState.update {
                    it.copy(
                        isReviewMode = true,
                        showAnswer = false
                    )
                }
                startTimer(vocabState.value)
                return@launch
            }

            uiState.update { it.copy(isLoading = true, error = null) }
            studyRepository.getNewWords(count, _currentOrder()).onSuccess { response ->
                val words = parseDailyWords(response)
                if (words.isEmpty()) {
                    uiState.update {
                        it.copy(isLoading = false, error = "当前词书没有新词了")
                    }
                    return@onSuccess
                }
                uiState.update { it.copy(isLoading = false) }
                sessionStore?.clear()
                vocabState.update {
                    it.copy(
                        learnWords = words,
                        isNewWordsMode = true,
                        isReviewMode = true,
                        sessionDate = todayKey(),
                        sessionId = newSessionId(),
                        sessionElapsedSeconds = 0,
                        currentCardIndex = 0,
                        showAnswer = false,
                        sessionSummary = null,
                        sessionStats = null,
                        reviewResults = emptyList(),
                        redoCounts = emptyMap()
                    )
                }
                startTimer(vocabState.value)
            }.onFailure { error ->
                uiState.update {
                    it.copy(
                        isLoading = false,
                        error = error.message ?: "加载新词失败"
                    )
                }
            }
        }
    }

    /** 获取当前排序模式（复习/新词共用） */
    private fun _currentOrder(): String = vocabState.value.wordOrder

    /**
     * 提交当前卡片的复习质量评分
     *
     * @param quality 复习质量评分（通常 0-5）
     *
     * 乐观更新：立即在本地推进到下一张卡片（若已是最后一张则调用 [finishSession] 结束会话），
     * 评分再在后台异步同步到后端，响应仅用于刷新会话统计（streak 等）。
     */
    fun submitReview(quality: Int) {
        // 乐观更新：先同步推进本地卡片状态（立即切卡、翻回问题面），
        // 再在后台把评分同步到后端。这样点 Again/Hard/Good/Easy 不再卡顿。
        val vocab = vocabState.value
        val currentIdx = vocab.currentCardIndex
        val currentList = vocab.learnWords
        val currentWord = currentList.getOrNull(currentIdx) ?: return
        var shouldFinishSession = false

        // 结算页“会/不会”只区分 Again 与其余评分：Hard 表示知道但需要加强，
        // 因此记为“会”；后端仍收到原始 quality，FSRS 排程语义完全不变。
        val known = quality >= 2
        val firstTranslation = currentWord.translations.firstOrNull()?.translation ?: ""
        val resultItem = ReviewResultItem(
            word = currentWord.word,
            known = known,
            translation = firstTranslation
        )

        // Again(quality<=1)：按 Anki 语义在本轮内重排到队尾当场再背，
        // 避免「点 1m 和 10m 没区别」「复习完又来一遍」的错觉。
        // 每词最多重排 2 次，防止无限 Again 死循环。
        // 注意重排计数用独立的 redoCounts（reviewResults 是按词去重的，
        // 不能用于计数，否则恒 < 2 导致无限重排）。
        val redoCount = vocab.redoCounts[currentWord.word] ?: 0
        val shouldRedo = quality <= 1 && redoCount < 2

        if (shouldRedo) {
            // 把当前词复制一份追加到队尾，索引前进 1（队尾副本稍后再次出现）
            val newList = currentList.toMutableList().apply { add(currentWord) }
            vocabState.update {
                it.copy(
                    learnWords = newList,
                    currentCardIndex = currentIdx + 1,
                    showAnswer = false,
                    reviewResults = dedupeResults(it.reviewResults + resultItem),
                    redoCounts = it.redoCounts + (currentWord.word to (redoCount + 1))
                )
            }
            persistUnfinishedSession()
        } else {
            val nextIndex = currentIdx + 1
            if (nextIndex >= currentList.size) {
                // 进入结算前清空本轮重置的临时列表，保留 reviewResults（去重）
                vocabState.update { it.copy(reviewResults = dedupeResults(it.reviewResults + resultItem)) }
                sessionStore?.clear()
                shouldFinishSession = true
            } else {
                vocabState.update {
                    it.copy(
                        currentCardIndex = nextIndex,
                        showAnswer = false,
                        reviewResults = dedupeResults(it.reviewResults + resultItem)
                    )
                }
                persistUnfinishedSession()
            }
        }

        // 后台同步后端：评分与之前完全一致，算法（FSRS 排程）不受影响。
        // 响应只用来刷新会话统计（streak 等）；失败时提示但不阻塞流程，
        // 该词会被后端视为未复习，下次继续推送（更保守，不会漏推）。
        val previousReviewSync = pendingReviewSyncJob
        pendingReviewSyncJob = scope.launch {
            previousReviewSync?.join()
            studyRepository.submitReview(currentWord.word, quality).onSuccess { response ->
                val stats = response["data"]?.jsonObject?.get("session_stats")?.jsonObject
                val sessionStats = stats?.let {
                    SessionStats(
                        active = it.boolean("active") ?: false,
                        duration = it.int("duration") ?: 0,
                        wordsReviewed = it.int("words_reviewed") ?: 0,
                        correctCount = it.int("correct_count") ?: 0,
                        accuracy = it.double("accuracy") ?: 0.0,
                        streak = it.int("streak") ?: 0
                    )
                }
                vocabState.update { it.copy(sessionStats = sessionStats) }
            }.onFailure { error ->
                uiState.update {
                    it.copy(error = error.message ?: "提交复习失败")
                }
            }
        }
        if (shouldFinishSession) finishSession()
    }

    /**
     * 结束当前复习会话（一组）。
     *
     * 收尾时先领取下一组：结算页的「继续下一组」必须对应真实存在的下一组，
     * 同时在拿不到下一组时把按钮降级成「返回」，避免点了之后才发现没词。
     */
    fun finishSession() {
        val reviewSync = pendingReviewSyncJob
        scope.launch {
            reviewSync?.join()
            studyRepository.endReviewSession().onSuccess { response ->
                sessionStore?.clear()
                timerManager?.endSession()
                val nextBatch = studyRepository.getDailyReviewBatch(
                    vocabState.value.reviewBatchSize,
                    _currentOrder()
                ).getOrNull()?.let { parseDailyWords(it) }.orEmpty()
                vocabState.update {
                    it.copy(
                        sessionSummary = response["data"],
                        isReviewMode = false,
                        // 本轮已收尾：清掉会话日期，后续刷新可以正常回落远端当天批次
                        sessionDate = "",
                        sessionId = "",
                        sessionElapsedSeconds = 0,
                        learnWords = nextBatch
                    )
                }
                onReviewProgressChanged()
            }.onFailure { error ->
                sessionStore?.clear()
                timerManager?.endSession()
                vocabState.update {
                    it.copy(
                        isReviewMode = false,
                        sessionDate = "",
                        sessionId = "",
                        sessionElapsedSeconds = 0
                    )
                }
                uiState.update {
                    it.copy(error = error.message ?: "结束会话失败")
                }
            }
        }
    }

    /** 设置是否展示当前卡片的答案 */
    fun setShowAnswer(show: Boolean) {
        vocabState.update { it.copy(showAnswer = show) }
    }

    /** 设置是否处于复习模式 */
    fun setIsReviewMode(isReview: Boolean) {
        vocabState.update { it.copy(isReviewMode = isReview) }
        // 退出全屏复习不等于结束会话（队列里可能还有 Again 重排的词），
        // 计时只暂停并落盘，下次进来接着算，不把这段前台时间丢掉。
        if (!isReview) {
            val elapsed = timerManager?.currentSeconds()
            timerManager?.pauseSession()
            if (elapsed != null) {
                vocabState.update { it.copy(sessionElapsedSeconds = elapsed) }
            }
            persistUnfinishedSession()
            // 中途退出也刷新：今日已背、词书进度、待复习数要反映已提交的评分
            onReviewProgressChanged()
        }
    }

    /** 设置会话总结数据 */
    fun setSessionSummary(summary: Any?) {
        vocabState.update { it.copy(sessionSummary = summary) }
        if (summary != null) sessionStore?.clear()
    }
}