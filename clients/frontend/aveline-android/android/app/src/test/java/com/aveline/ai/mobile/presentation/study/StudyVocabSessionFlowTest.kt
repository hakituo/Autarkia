package com.aveline.ai.mobile.presentation.study

import com.aveline.ai.mobile.domain.repository.StudyRepository
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 背词会话的状态衔接（2026-10-26 体验优化）。
 *
 * 1. 最后一张评分后立即进入结算，不等结束会话 / 预取下一组的网络请求
 * 2. 已进入结算后再点评分不会对同一个词重复提交
 * 3. 开始复习请求在途时连点只发一次请求，入口处于 launching 态
 * 4. 从结算页「继续」：成功时同一次更新里清掉结算并进入复习；失败时留在结算页
 */
@OptIn(ExperimentalCoroutinesApi::class)
class StudyVocabSessionFlowTest {

    private fun word(name: String) = DailyWord(
        word = name,
        translations = listOf(WordTranslation(type = "n.", translation = "释义 $name")),
        phrases = null,
        sentences = null,
        us = null,
        uk = null,
        status = "review",
        dueTime = null
    )

    private fun ok(): JsonObject = buildJsonObject { put("data", buildJsonObject { put("ok", true) }) }

    private fun words(vararg names: String): JsonObject = buildJsonObject {
        put(
            "data", buildJsonArray {
                names.forEach { name ->
                    add(buildJsonObject { put("word", name); put("status", "review") })
                }
            }
        )
    }

    private fun manager(
        repo: StudyRepository,
        state: VocabUiState
    ): Triple<StudyVocabReviewManager, MutableStateFlow<VocabUiState>, MutableStateFlow<StudyUiState>> {
        val uiState = MutableStateFlow(StudyUiState())
        val vocabState = MutableStateFlow(state)
        val m = StudyVocabReviewManager(
            CoroutineScope(UnconfinedTestDispatcher()), uiState, vocabState, repo
        )
        return Triple(m, vocabState, uiState)
    }

    @Test
    fun `最后一张评分后网络未返回也已进入结算`() {
        val repo = mockk<StudyRepository>()
        val gate = CompletableDeferred<Unit>()
        coEvery { repo.submitReview(any(), any()) } returns Result.success(ok())
        coEvery { repo.endReviewSession() } coAnswers {
            gate.await()
            Result.success(ok())
        }
        coEvery { repo.getDailyReviewBatch(any(), any()) } returns Result.success(words("next"))
        val (m, vocabState, _) = manager(
            repo,
            VocabUiState(learnWords = listOf(word("apple")), isReviewMode = true, showAnswer = true)
        )

        m.submitReview(3)

        // 结束会话还挂着：结算已展示，继续按钮处于准备态
        assertFalse(vocabState.value.isReviewMode)
        assertNotNull(vocabState.value.sessionSummary)
        assertTrue(vocabState.value.isFinishing)

        gate.complete(Unit)
        assertFalse(vocabState.value.isFinishing)
        assertEquals("next", vocabState.value.learnWords.single().word)
    }

    @Test
    fun `进入结算后重复点评分只提交一次`() {
        val repo = mockk<StudyRepository>()
        coEvery { repo.submitReview(any(), any()) } returns Result.success(ok())
        coEvery { repo.endReviewSession() } returns Result.success(ok())
        coEvery { repo.getDailyReviewBatch(any(), any()) } returns Result.success(words())
        val (m, _, _) = manager(
            repo,
            VocabUiState(learnWords = listOf(word("apple")), isReviewMode = true, showAnswer = true)
        )

        m.submitReview(3)
        m.submitReview(3)

        coVerify(exactly = 1) { repo.submitReview("apple", 3) }
    }

    @Test
    fun `结束会话失败时留在结算页并提示`() {
        val repo = mockk<StudyRepository>()
        coEvery { repo.submitReview(any(), any()) } returns Result.success(ok())
        coEvery { repo.endReviewSession() } returns Result.failure(RuntimeException("timeout"))
        val (m, vocabState, uiState) = manager(
            repo,
            VocabUiState(learnWords = listOf(word("apple")), isReviewMode = true, showAnswer = true)
        )

        m.submitReview(3)

        assertNotNull(vocabState.value.sessionSummary)
        assertFalse(vocabState.value.isFinishing)
        assertTrue(vocabState.value.learnWords.isEmpty())
        assertNotNull(uiState.value.error)
    }

    @Test
    fun `开始复习请求在途时连点只发一次请求`() {
        val repo = mockk<StudyRepository>()
        val gate = CompletableDeferred<Unit>()
        coEvery { repo.getDailyReviewBatch(any(), any()) } coAnswers {
            gate.await()
            Result.success(words("alpha"))
        }
        coEvery { repo.startReviewSession() } returns Result.success(ok())
        val (m, vocabState, _) = manager(repo, VocabUiState())

        m.startReview()
        assertEquals(VocabLaunch.REVIEW, vocabState.value.launching)
        m.startReview()

        gate.complete(Unit)
        coVerify(exactly = 1) { repo.getDailyReviewBatch(any(), any()) }
        assertNull(vocabState.value.launching)
        assertTrue(vocabState.value.isReviewMode)
    }

    @Test
    fun `结算页继续背新词成功时同一次更新进入复习`() {
        val repo = mockk<StudyRepository>()
        coEvery { repo.getNewWords(any(), any()) } returns Result.success(words("fresh"))
        val (m, vocabState, _) = manager(
            repo,
            VocabUiState(
                isNewWordsMode = true,
                sessionSummary = "local",
                reviewResults = listOf(ReviewResultItem("apple", true, "释义 apple"))
            )
        )

        m.startNewWordsSession()

        assertTrue(vocabState.value.isReviewMode)
        assertNull(vocabState.value.sessionSummary)
        assertNull(vocabState.value.launching)
        assertEquals("fresh", vocabState.value.learnWords.single().word)
    }

    @Test
    fun `没有新词时留在原页面并给出提示`() {
        val repo = mockk<StudyRepository>()
        coEvery { repo.getNewWords(any(), any()) } returns Result.success(words())
        val (m, vocabState, uiState) = manager(
            repo,
            VocabUiState(isNewWordsMode = true, sessionSummary = "local")
        )

        m.startNewWordsSession()

        assertFalse(vocabState.value.isReviewMode)
        assertNotNull(vocabState.value.sessionSummary)
        assertNull(vocabState.value.launching)
        assertEquals("当前词书没有新词了", uiState.value.error)
    }
}
