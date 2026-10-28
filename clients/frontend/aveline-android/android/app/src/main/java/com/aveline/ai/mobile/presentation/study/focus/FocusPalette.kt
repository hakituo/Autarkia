package com.aveline.ai.mobile.presentation.study.focus

import androidx.compose.ui.graphics.Color
import com.aveline.ai.mobile.presentation.study.FocusPhase
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Mist
import com.aveline.ai.mobile.presentation.theme.TextPrimary

/**
 * 专注页的阶段色与轮次口径。
 *
 * 阶段色压低成同一明度带：专注用浅色、短休息用鼠尾草绿、长休息用雾蓝，
 * 替换掉原来的天蓝 / Emerald / #64B5F6。
 *
 * 这里的函数都是纯逻辑（不依赖 Composable），便于单测；UI 只做排版。
 */

/** 圆环当前的填充比例（剩余 / 总时长）。 */
internal fun focusRingProgress(remainingSeconds: Int, totalSeconds: Int): Float {
    if (totalSeconds <= 0) return 0f
    return (remainingSeconds.toFloat() / totalSeconds.toFloat()).coerceIn(0f, 1f)
}

/** `mm:ss`；负数按 0 处理，避免阶段切换瞬间出现 `-1:59`。 */
internal fun focusClockText(remainingSeconds: Int): String {
    val safe = remainingSeconds.coerceAtLeast(0)
    return "%02d:%02d".format(safe / 60, safe % 60)
}

internal fun focusPhaseColor(phase: FocusPhase): Color = when (phase) {
    FocusPhase.WORK -> TextPrimary
    FocusPhase.BREAK -> Accent
    FocusPhase.LONG_BREAK -> Mist
}

internal fun focusPhaseLabel(phase: FocusPhase): String = when (phase) {
    FocusPhase.WORK -> "专注中"
    FocusPhase.BREAK -> "休息一下"
    FocusPhase.LONG_BREAK -> "长休息"
}

/**
 * 本轮已经走过的专注周期数。
 *
 * 长休息时本轮刚好走满，取满值而不是回绕成 0 —— 否则「本轮 0 / 4」会让人以为白干了。
 */
internal fun focusRoundProgress(
    completedCycles: Int,
    cyclesPerRound: Int,
    phase: FocusPhase
): Int {
    val per = cyclesPerRound.coerceAtLeast(1)
    val done = completedCycles.coerceAtLeast(0) % per
    return if (done == 0 && completedCycles > 0 && phase != FocusPhase.WORK) per else done
}

internal fun focusRoundText(
    completedCycles: Int,
    cyclesPerRound: Int,
    phase: FocusPhase
): String {
    val per = cyclesPerRound.coerceAtLeast(1)
    return "${focusRoundProgress(completedCycles, per, phase)} / $per"
}

/** 还差几个专注周期进长休息；长休息当下为 0。 */
internal fun focusCyclesToLongBreak(
    completedCycles: Int,
    cyclesPerRound: Int,
    phase: FocusPhase
): Int {
    val per = cyclesPerRound.coerceAtLeast(1)
    return (per - focusRoundProgress(completedCycles, per, phase)).coerceAtLeast(0)
}

/** 本轮进度点：已走过 = 实心，当前 = 半亮，未到 = 暗点。 */
internal enum class FocusDotState { FILLED, CURRENT, EMPTY }

internal fun focusDots(progress: Int, cyclesPerRound: Int): List<FocusDotState> {
    val per = cyclesPerRound.coerceAtLeast(1)
    return (0 until per).map { index ->
        when {
            index < progress -> FocusDotState.FILLED
            index == progress -> FocusDotState.CURRENT
            else -> FocusDotState.EMPTY
        }
    }
}

internal fun focusDotColor(dot: FocusDotState): Color = when (dot) {
    FocusDotState.FILLED -> Color(0xFFECEBE7)
    FocusDotState.CURRENT -> Color(0x80ECEBE7)
    FocusDotState.EMPTY -> Color(0x29FFFFFF)
}
