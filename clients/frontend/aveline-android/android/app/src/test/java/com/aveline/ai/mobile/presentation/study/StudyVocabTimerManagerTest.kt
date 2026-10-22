package com.aveline.ai.mobile.presentation.study

import com.aveline.ai.mobile.domain.repository.StudyRepository
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * StudyVocabTimerManager 回归：前台累计、后台暂停、周期上报与断点续背。
 *
 * 时钟直接绑定虚拟调度器时间，`advanceTimeBy` 同时驱动机器里的 tick 与计时。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class StudyVocabTimerManagerTest {

    private fun repo(): StudyRepository {
        val repository = mockk<StudyRepository>()
        coEvery { repository.reportVocabStudyTime(any(), any(), any()) } returns
            Result.success(JsonObject(emptyMap()))
        return repository
    }

    private fun TestScope.manager(
        repository: StudyRepository,
        onReported: (Boolean) -> Unit = {}
    ): StudyVocabTimerManager = StudyVocabTimerManager(
        scope = backgroundScope,
        studyRepository = repository,
        timer = VocabStudyTimer { testScheduler.currentTime },
        tickIntervalMillis = 1_000L,
        reportIntervalMillis = 30_000L,
        onReported = onReported
    )

    @Test
    fun `进入会话即开始计时并每秒刷新展示值`() = runTest {
        val manager = manager(repo())

        manager.startSession("s1", "review")
        advanceTimeBy(5_500)
        runCurrent()

        assertEquals(5, manager.currentSeconds())
        assertEquals(5, manager.elapsedSeconds.value)
    }

    @Test
    fun `切后台立即暂停并上报累计值`() = runTest {
        val repository = repo()
        val manager = manager(repository)

        manager.startSession("s1", "review")
        advanceTimeBy(42_500)
        runCurrent()
        manager.onBackground()
        runCurrent()

        coVerify { repository.reportVocabStudyTime("s1", 42, "review") }

        val paused = manager.currentSeconds()
        advanceTimeBy(60_000)
        runCurrent()

        assertEquals(paused, manager.currentSeconds())
        assertEquals(paused, manager.elapsedSeconds.value)
    }

    @Test
    fun `前台每30秒周期上报一次累计秒数`() = runTest {
        val repository = repo()
        val manager = manager(repository)

        manager.startSession("s1", "review")
        advanceTimeBy(31_000)
        runCurrent()
        coVerify { repository.reportVocabStudyTime("s1", 30, "review") }

        advanceTimeBy(31_000)
        runCurrent()
        coVerify { repository.reportVocabStudyTime("s1", 60, "review") }
    }

    @Test
    fun `同一sessionId重新进入不重置累计`() = runTest {
        val manager = manager(repo())

        manager.startSession("s1", "review")
        advanceTimeBy(10_500)
        runCurrent()
        manager.pauseSession()
        runCurrent()
        assertEquals(10, manager.currentSeconds())

        // 断点续背：同一 sessionId 应接着算，而不是从 0 重新开始
        manager.startSession("s1", "review")
        advanceTimeBy(5_500)
        runCurrent()

        assertEquals(15, manager.currentSeconds())
    }

    @Test
    fun `一组背完结算最终时长并重置`() = runTest {
        val repository = repo()
        val finals = mutableListOf<Boolean>()
        val manager = manager(repository) { finals += it }

        manager.startSession("s1", "new_words")
        advanceTimeBy(45_500)
        runCurrent()
        manager.endSession()
        runCurrent()

        coVerify { repository.reportVocabStudyTime("s1", 45, "new_words") }
        assertTrue(finals.isNotEmpty())
        assertEquals(0, manager.currentSeconds())
    }
}
