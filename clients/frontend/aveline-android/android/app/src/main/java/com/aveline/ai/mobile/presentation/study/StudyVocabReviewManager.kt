package com.aveline.ai.mobile.presentation.study

import com.aveline.ai.mobile.domain.repository.StudyRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.jsonObject
import java.time.LocalDate

/** 后端结算还没回来时的占位：结算页只读本地 reviewResults，有值即可展示。 */
private const val LOCAL_SUMMARY = "local"

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
            ?.takeIf { it in VOCAB_BATCH_SIZE_OPTIONS }
            ?.let { batchSize -> vocabState.update { it.copy(newWordsBatchSize = batchSize) } }
        sessionStore?.getReviewBatchSize()
            ?.takeIf { it in VOCAB_BATCH_SIZE_OPTIONS }
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
        if (batchSize !in VOCAB_BATCH_SIZE_OPTIONS) return
        sessionStore?.saveNewWordsBatchSize(batchSize)
        vocabState.update { it.copy(newWordsBatchSize = batchSize) }
    }

    fun setReviewBatchSize(batchSize: Int) {
        if (batchSize !in VOCAB_BATCH_SIZE_OPTIONS) return
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
     * 开始一次词汇复习会话。
     *
     * 与背新词一致按组领取：每次只拉 [VocabUiState.reviewBatchSize] 个待复习词，
     * 完成一组后再领下一组。后端当天队列会过滤掉已评分的词，所以无需游标。
     * 中途退出（本地队列未走完）仍从断点续背，不重新拉取。
     */
    fun startReview() {
        // 防重入：请求在途或上一组还在收尾时，连点只算一次
        if (vocabState.value.launching != null || vocabState.value.isFinishing) return
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
            vocabState.update { it.copy(launching = VocabLaunch.REVIEW) }
            uiState.update { it.copy(error = null) }
            val batchResult = studyRepository.getDailyReviewBatch(
                current.reviewBatchSize,
                _currentOrder()
            )
            val words = batchResult.getOrNull()?.let { parseDailyWords(it) }
            if (words == null) {
                vocabState.update { it.copy(launching = null) }
                uiState.update {
                    it.copy(error = batchResult.exceptionOrNull()?.message ?: "加载复习词失败")
                }
                return@launch
            }
            if (words.isEmpty()) {
                uiState.update { it.copy(successMessage = "今天的复习已经全部完成") }
                vocabState.update {
                    it.copy(
                        launching = null,
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
                // 同一次更新里清掉结算并进入复习：结算页直接推到复习页，中间不回主页
                vocabState.update {
                    it.copy(
                        launching = null,
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
                vocabState.update { it.copy(launching = null) }
                uiState.update { it.copy(error = error.message ?: "开始复习失败") }
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
        // 防重入；上一组收尾（评分同步）完成前不领新词，否则刚背的词可能又被发回来
        if (vocabState.value.launching != null || vocabState.value.isFinishing) return
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

            vocabState.update { it.copy(launching = VocabLaunch.NEW_WORDS) }
            uiState.update { it.copy(error = null) }
            studyRepository.getNewWords(count, _currentOrder()).onSuccess { response ->
                val words = parseDailyWords(response)
                if (words.isEmpty()) {
                    vocabState.update { it.copy(launching = null) }
                    uiState.update { it.copy(error = "当前词书没有新词了") }
                    return@onSuccess
                }
                sessionStore?.clear()
                vocabState.update {
                    it.copy(
                        launching = null,
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
                vocabState.update { it.copy(launching = null) }
                uiState.update { it.copy(error = error.message ?: "加载新词失败") }
            }
        }
    }

    /**
     * 切换词书后丢掉属于旧书的未完成新词队列（复习队列与词书无关，保留）。
     */
    fun discardNewWordsQueue() {
        val current = vocabState.value
        if (!current.isNewWordsMode || current.isReviewMode || current.sessionSummary != null) return
        if (current.learnWords.isEmpty() && current.sessionDate.isEmpty()) return
        sessionStore?.clear()
        timerManager?.endSession()
        vocabState.update {
            it.copy(
                learnWords = emptyList(),
                sessionDate = "",
                sessionId = "",
                sessionElapsedSeconds = 0,
                currentCardIndex = 0,
                showAnswer = false,
                reviewResults = emptyList(),
                redoCounts = emptyMap()
            )
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
        // 已经离开复习（最后一张已进结算）时再点评分一律忽略，杜绝同一个词重复提交
        if (!vocab.isReviewMode || vocab.sessionSummary != null || vocab.isFinishing) return
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
                // 保留 reviewResults（去重）；结算页由 finishSession 立即打开
                vocabState.update { it.copy(reviewResults = dedupeResults(it.reviewResults + resultItem)) }
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
     * 结算页只依赖本地的 reviewResults，所以先在同一次更新里切到结算（不等网络），
     * 再在后台依次：等评分同步 → 结束会话 → 预取下一组。预取完成前结算页的
     * 「继续」按钮转圈；拿不到下一组时按钮降级成「返回」，避免点了才发现没词。
     */
    fun finishSession() {
        if (vocabState.value.isFinishing) return
        sessionStore?.clear()
        timerManager?.endSession()
        vocabState.update {
            it.copy(
                isReviewMode = false,
                showAnswer = false,
                isFinishing = true,
                sessionSummary = it.sessionSummary ?: LOCAL_SUMMARY,
                // 本轮已收尾：清掉会话日期，后续刷新可以正常回落远端当天批次
                sessionDate = "",
                sessionId = "",
                sessionElapsedSeconds = 0
            )
        }
        val reviewSync = pendingReviewSyncJob
        scope.launch {
            reviewSync?.join()
            studyRepository.endReviewSession().onSuccess { response ->
                val nextBatch = studyRepository.getDailyReviewBatch(
                    vocabState.value.reviewBatchSize,
                    _currentOrder()
                ).getOrNull()?.let { parseDailyWords(it) }.orEmpty()
                vocabState.update {
                    it.copy(
                        // 用户可能已经离开结算页，此时不再把结算补回来
                        sessionSummary = it.sessionSummary?.let { _ -> response["data"] ?: LOCAL_SUMMARY },
                        isFinishing = false,
                        learnWords = nextBatch
                    )
                }
                onReviewProgressChanged()
            }.onFailure { error ->
                // 结算照常展示本地结果，不把用户踢回主页；没有下一组可继续复习
                vocabState.update { it.copy(isFinishing = false, learnWords = emptyList()) }
                uiState.update {
                    it.copy(error = "结束会话没同步上：${error.message ?: "网络异常"}，评分已逐词提交")
                }
                onReviewProgressChanged()
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