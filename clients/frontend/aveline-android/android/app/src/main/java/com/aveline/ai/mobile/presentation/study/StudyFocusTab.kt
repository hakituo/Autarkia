package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.study.focus.FocusBottomPanel
import com.aveline.ai.mobile.presentation.study.focus.FocusControls
import com.aveline.ai.mobile.presentation.study.focus.FocusRing
import com.aveline.ai.mobile.presentation.study.focus.FocusTargetSelector
import com.aveline.ai.mobile.presentation.study.focus.focusDots
import com.aveline.ai.mobile.presentation.study.focus.focusRoundProgress

/**
 * 番茄钟（专注）Tab。
 *
 * 整页只剩一个大计时：事项名在顶部（未开始可点改、开始后收成一行文字），
 * 中间是 3dp 细环 + 64sp Light 数字 + 本轮小点，下面是两个描边圆按钮和
 * 一个 76dp 实心按钮；底部未开始时是三个紧凑步进器，开始后换成三格统计。
 *
 * 排版块在同包 [com.aveline.ai.mobile.presentation.study.focus] 下拆开，
 * 本文件只负责拼装与滚动兜底（窄屏时上半部分自己滚，底部设置不跟着走）。
 */
@Composable
fun StudyFocusTab(
    focusState: StudyFocusState,
    onToggleTimer: () -> Unit,
    onReset: () -> Unit,
    onSkipPhase: () -> Unit,
    onWorkMinutesChange: (Int) -> Unit,
    onBreakMinutesChange: (Int) -> Unit,
    onLongBreakMinutesChange: (Int) -> Unit,
    onFocusNameChange: (String) -> Unit = {}
) {
    val totalSeconds = focusTotalSeconds(focusState)
    // 「开始过一次」= 正在计时，或当前阶段已经走了几秒（暂停中也算）：
    // 暂停不该让设置面板和事项输入框突然回来抢版面，重置才是回到可编辑态。
    val started = focusState.isRunning || focusState.remainingSeconds < totalSeconds
    val roundProgress = focusRoundProgress(
        completedCycles = focusState.completedCycles,
        cyclesPerRound = focusState.cyclesBeforeLongBreak,
        phase = focusState.phase
    )

    Column(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
                .verticalScroll(rememberScrollState()),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Spacer(modifier = Modifier.height(16.dp))

            FocusTargetSelector(
                name = focusState.focusName,
                collapsed = started,
                onNameChange = onFocusNameChange
            )

            Spacer(modifier = Modifier.height(26.dp))

            FocusRing(
                phase = focusState.phase,
                remainingSeconds = focusState.remainingSeconds,
                totalSeconds = totalSeconds,
                dotStates = focusDots(roundProgress, focusState.cyclesBeforeLongBreak)
            )

            Spacer(modifier = Modifier.height(30.dp))

            FocusControls(
                isRunning = focusState.isRunning,
                onToggle = onToggleTimer,
                onReset = onReset,
                onSkip = onSkipPhase
            )

            Spacer(modifier = Modifier.height(24.dp))
        }

        FocusBottomPanel(
            state = focusState,
            showStats = started,
            onWorkMinutesChange = onWorkMinutesChange,
            onBreakMinutesChange = onBreakMinutesChange,
            onLongBreakMinutesChange = onLongBreakMinutesChange
        )
    }
}

/** 当前阶段的总时长；阶段切换瞬间也不会出现除零。 */
internal fun focusTotalSeconds(state: StudyFocusState): Int = when (state.phase) {
    FocusPhase.WORK -> state.workMinutes * 60
    FocusPhase.BREAK -> state.breakMinutes * 60
    FocusPhase.LONG_BREAK -> state.longBreakMinutes * 60
}.coerceAtLeast(1)
