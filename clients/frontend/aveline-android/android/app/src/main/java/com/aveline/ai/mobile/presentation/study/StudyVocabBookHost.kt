package com.aveline.ai.mobile.presentation.study

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import com.aveline.ai.mobile.presentation.study.vocab.VocabBookDetailScreen
import com.aveline.ai.mobile.presentation.study.vocab.VocabBookListScreen
import com.aveline.ai.mobile.presentation.study.vocab.VocabMistakesScreen
import com.aveline.ai.mobile.presentation.study.vocab.VocabReviewScreen
import com.aveline.ai.mobile.presentation.study.vocab.VocabSummaryScreen
import kotlinx.coroutines.flow.StateFlow

/**
 * 词汇模块全屏层（复习 / 结算 / 词书列表 / 词书详情 / 错题本）。
 *
 * 只有这一层负责进出场：主页状态 [VocabScreen.HOME] 不画任何东西，
 * 学习页本体在下面由 [rememberVocabBaseCover] 跟随让位，所以退出时
 * 页面是完整地被带走，不会先变空白再整体淡出。转场规则见 `VocabTransitions.kt`。
 *
 * 子页面状态 [VocabSubScreen] 由 [StudyScreenV2] 提升持有并透传。
 */
@Composable
fun StudyVocabBookHost(
    uiState: VocabUiState,
    /** 当前复习会话累计前台秒数（背单词自动计时）。 */
    elapsedSeconds: StateFlow<Int>,
    vocabSubScreen: VocabSubScreen,
    onVocabSubScreenChange: (VocabSubScreen) -> Unit,
    onSetShowAnswer: (Boolean) -> Unit,
    onSubmitReview: (String) -> Unit,
    onSetIsReviewMode: (Boolean) -> Unit,
    onSetSessionSummary: (String) -> Unit,
    onSwitchBook: (String) -> Unit,
    onLoadBookWords: () -> Unit = {},
    onStartNewWords: () -> Unit = {},
    onStartReview: () -> Unit = {},
    modifier: Modifier = Modifier
) {
    val currentScreen = resolveVocabScreen(uiState, vocabSubScreen)

    // 最近一次切换的方向：页面外壳据此决定遮罩出现在进场还是离场
    var previousScreen by remember { mutableStateOf(currentScreen) }
    val move = remember(currentScreen) { vocabMove(previousScreen, currentScreen) }
    SideEffect { previousScreen = currentScreen }

    // 每页离场时冻结在离开那一刻的数据：否则结算页会在滑走途中被清空，
    // 复习页会在滑走途中换成下一组的词。
    val snapshots = remember { HashMap<VocabScreen, VocabUiState>() }
    snapshots[currentScreen] = uiState

    // 进入背词会话后，子页面栈回到主页：关闭会话直接回词汇主页，不再弹回词书详情
    LaunchedEffect(uiState.isReviewMode) {
        if (uiState.isReviewMode && vocabSubScreen != VocabSubScreen.DASHBOARD) {
            onVocabSubScreenChange(VocabSubScreen.DASHBOARD)
        }
    }

    // 系统返回键：在词汇全屏层内逐级返回，不直接退出到聊天主页
    BackHandler(enabled = currentScreen != VocabScreen.HOME) {
        when (currentScreen) {
            VocabScreen.REVIEW -> onSetIsReviewMode(false)
            VocabScreen.SUMMARY -> {
                onSetSessionSummary("")
                onVocabSubScreenChange(VocabSubScreen.DASHBOARD)
            }
            VocabScreen.BOOK_DETAIL -> onVocabSubScreenChange(VocabSubScreen.BOOK_LIST)
            else -> onVocabSubScreenChange(VocabSubScreen.DASHBOARD)
        }
    }

    AnimatedContent(
        targetState = currentScreen,
        transitionSpec = { vocabTransform(vocabMove(initialState, targetState)) },
        modifier = modifier.fillMaxSize(),
        label = "vocab_host"
    ) { screen ->
        if (screen == VocabScreen.HOME) {
            // 主页由下层的学习页本体展示；这里留空且不拦截点击
            Box(modifier = Modifier.fillMaxSize())
            return@AnimatedContent
        }
        val state = if (screen == currentScreen) uiState else snapshots[screen] ?: uiState
        VocabPage(move = move) {
            when (screen) {
                VocabScreen.REVIEW -> VocabReviewScreen(
                    uiState = state,
                    elapsedSeconds = elapsedSeconds,
                    onSetShowAnswer = onSetShowAnswer,
                    onSubmitReview = onSubmitReview,
                    onSetIsReviewMode = onSetIsReviewMode
                )

                VocabScreen.SUMMARY -> VocabSummaryScreen(
                    reviewResults = state.reviewResults,
                    isNewWordsMode = state.isNewWordsMode,
                    // 复习分组：结算后台预取下一组，空组时不再诱导点击
                    hasMore = state.isNewWordsMode || state.learnWords.isNotEmpty(),
                    preparing = state.isFinishing,
                    launching = state.launching != null,
                    // 不先清空结算：请求成功后由管理器在同一次更新里切到复习，
                    // 全屏层不会出现「退回主页再弹进来」的往返
                    onContinue = {
                        if (state.isNewWordsMode) onStartNewWords() else onStartReview()
                    },
                    onExit = {
                        onSetSessionSummary("")
                        onVocabSubScreenChange(VocabSubScreen.DASHBOARD)
                    }
                )

                VocabScreen.BOOK_LIST -> VocabBookListScreen(
                    uiState = state,
                    onBack = { onVocabSubScreenChange(VocabSubScreen.DASHBOARD) },
                    onSelectBook = { filename ->
                        // 当前这本再点一次不重复切书，只打开详情
                        if (filename != state.currentBook) onSwitchBook(filename)
                        onVocabSubScreenChange(VocabSubScreen.BOOK_DETAIL)
                    }
                )

                VocabScreen.BOOK_DETAIL -> VocabBookDetailScreen(
                    uiState = state,
                    onBack = { onVocabSubScreenChange(VocabSubScreen.BOOK_LIST) },
                    onStartNewWords = onStartNewWords,
                    onLoadBookWords = onLoadBookWords
                )

                VocabScreen.MISTAKES -> VocabMistakesScreen(
                    uiState = state,
                    onBack = { onVocabSubScreenChange(VocabSubScreen.DASHBOARD) }
                )

                VocabScreen.HOME -> Unit
            }
        }
    }
}
