package com.aveline.ai.mobile.presentation.study

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * VocabStudyTimer 纯逻辑回归：只累计前台可见时间。
 *
 * 时钟注入可控值，不依赖真实 System.nanoTime()。
 */
class VocabStudyTimerTest {

    private var now = 0L
    private val timer = VocabStudyTimer { now }

    @Test
    fun `暂停期间的后台时间不计入`() {
        timer.start()
        now = 5_000
        timer.pause()

        // 后台待了 60 秒，回到前台后才继续累加
        now = 65_000
        timer.resume()
        now = 70_000

        assertEquals(10, timer.elapsedSeconds())
    }

    @Test
    fun `重复resume不会重复计时`() {
        timer.start()
        now = 1_000
        timer.resume()
        now = 2_000
        timer.resume()
        now = 3_000

        assertEquals(3, timer.elapsedSeconds())
    }

    @Test
    fun `start带初始值时从断点续算`() {
        timer.start(initialMillis = 60_000L)
        now = 30_000

        assertEquals(90, timer.elapsedSeconds())
        assertEquals(90_000L, timer.elapsedMillis())
    }

    @Test
    fun `reset清空累计并停止计时`() {
        timer.start()
        now = 8_000
        timer.pause()

        timer.reset()

        assertFalse(timer.isRunning)
        assertEquals(0, timer.elapsedSeconds())
        assertEquals(0L, timer.elapsedMillis())
    }

    @Test
    fun `未start时计时为0`() {
        assertFalse(timer.isRunning)
        assertEquals(0, timer.elapsedSeconds())

        timer.resume()
        assertTrue(timer.isRunning)
    }
}
