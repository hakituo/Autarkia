package com.aveline.ai.mobile.presentation.study

import com.aveline.ai.mobile.domain.models.StudyPlanItem
import com.aveline.ai.mobile.presentation.study.focus.FocusDotState
import com.aveline.ai.mobile.presentation.study.focus.focusClockText
import com.aveline.ai.mobile.presentation.study.focus.focusCyclesToLongBreak
import com.aveline.ai.mobile.presentation.study.focus.focusDots
import com.aveline.ai.mobile.presentation.study.focus.focusRingProgress
import com.aveline.ai.mobile.presentation.study.focus.focusRoundProgress
import com.aveline.ai.mobile.presentation.study.focus.focusRoundText
import com.aveline.ai.mobile.presentation.study.today.formatPlanSpan
import com.aveline.ai.mobile.presentation.study.today.formatTodayDateLabel
import com.aveline.ai.mobile.presentation.study.today.nextTaskDetail
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「今天 / 专注」改版后的纯文案与轮次口径。
 *
 * 排版不算，但这些数字口径一旦算错，页面上的「还差 / 计划共 / 本轮 / 到长休息」
 * 会一起错，所以单独锁住。
 */
class StudyTodayFormatTest {

    @Test
    fun `plan span pads single digit minutes`() {
        assertEquals("0min", formatPlanSpan(0))
        assertEquals("45min", formatPlanSpan(45))
        assertEquals("4h", formatPlanSpan(240))
        assertEquals("4h 05min", formatPlanSpan(245))
        assertEquals("2h 35min", formatPlanSpan(155))
    }

    @Test
    fun `today date label keeps chinese month day`() {
        val label = formatTodayDateLabel("2026-10-25")
        assertTrue(label, label.startsWith("10月25日"))
        assertEquals("", formatTodayDateLabel(""))
    }

    @Test
    fun `next task detail shows tracked minutes only when present`() {
        val tracked = StudyPlanItem(
            id = "a",
            time = "14:00",
            estimatedDurationMinutes = 45,
            actualMinutes = 18.0
        )
        val untouched = StudyPlanItem(
            id = "b",
            time = "15:30",
            estimatedDurationMinutes = 50
        )
        val flexible = StudyPlanItem(id = "c", estimatedDurationMinutes = 20)

        assertEquals("14:00 · 已学 18 / 45 分钟", nextTaskDetail(tracked))
        assertEquals("15:30 · 50 分钟", nextTaskDetail(untouched))
        assertEquals("灵活 · 20 分钟", nextTaskDetail(flexible))
    }

    @Test
    fun `focus round progress counts inside the current round`() {
        assertEquals(2, focusRoundProgress(2, 4, FocusPhase.WORK))
        assertEquals("2 / 4", focusRoundText(2, 4, FocusPhase.WORK))
        assertEquals(2, focusCyclesToLongBreak(2, 4, FocusPhase.WORK))
    }

    @Test
    fun `long break closes the round instead of wrapping to zero`() {
        assertEquals(4, focusRoundProgress(4, 4, FocusPhase.LONG_BREAK))
        assertEquals("4 / 4", focusRoundText(4, 4, FocusPhase.LONG_BREAK))
        assertEquals(0, focusCyclesToLongBreak(4, 4, FocusPhase.LONG_BREAK))
        // 下一轮第一个番茄结束后仍在 WORK 才算重新开始
        assertEquals(0, focusRoundProgress(4, 4, FocusPhase.WORK))
    }

    @Test
    fun `focus dots mark passed current and upcoming cycles`() {
        assertEquals(
            listOf(
                FocusDotState.FILLED,
                FocusDotState.FILLED,
                FocusDotState.CURRENT,
                FocusDotState.EMPTY
            ),
            focusDots(2, 4)
        )
    }

    @Test
    fun `clock text never goes negative`() {
        assertEquals("00:00", focusClockText(-5))
        assertEquals("25:00", focusClockText(1500))
    }

    @Test
    fun `ring progress is clamped between zero and one`() {
        assertEquals(0f, focusRingProgress(0, 1500), 0.0001f)
        assertEquals(1f, focusRingProgress(1500, 1500), 0.0001f)
        assertEquals(0.2f, focusRingProgress(300, 1500), 0.0001f)
        assertEquals(0f, focusRingProgress(300, 0), 0.0001f)
    }
}
