package com.aveline.ai.mobile.presentation.study

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.aveline.ai.mobile.presentation.study.vocab.VocabBookDetailScreen
import com.aveline.ai.mobile.presentation.study.vocab.VocabBookListScreen
import com.aveline.ai.mobile.presentation.study.vocab.VocabMistakesScreen
import com.aveline.ai.mobile.presentation.study.vocab.VocabReviewScreen
import com.aveline.ai.mobile.presentation.study.vocab.VocabSummaryScreen
import com.aveline.ai.mobile.presentation.theme.Background
import kotlinx.coroutines.flow.StateFlow

/**
 * 词汇模块宿主组件。
 *
 * 接管全屏复习/结算与词汇子页面导航：
 * - 复习会话 [VocabReviewScreen]
 * - 会话结算 [VocabSummaryScreen]
 * - 词书列表 / 详情 [VocabBookListScreen] / [VocabBookDetailScreen]
 * - 错题本 [VocabMistakesScreen]
 *
 * 子页面状态 [VocabSubScreen] 由 [StudyScreenV2] 提升持有并透传，
 * 本组件只负责渲染、整页切换动画与返回键逐级回退逻辑。
 *
 * @param onSetSessionSummary 设置会话总结（传空字符串清除）
 * @param onLoadBookWords 进入词书详情时补齐单词列表
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
    onStartReview: () -> Unit = {}
) {
    // 当前应展示的页面（单一来源，供 AnimatedContent 做整页切换动画）
    val currentScreen = when {
        uiState.isReviewMode -> VocabScreen.REVIEW
        uiState.sessionSummary != null -> VocabScreen.SUMMARY
        vocabSubScreen == VocabSubScreen.BOOK_DETAIL -> VocabScreen.BOOK_DETAIL
        vocabSubScreen == VocabSubScreen.BOOK_LIST -> VocabScreen.BOOK_LIST
        vocabSubScreen == VocabSubScreen.MISTAKES -> VocabScreen.MISTAKES
        else -> VocabScreen.NONE
    }

    // 系统返回键：优先在词汇子页面/复习内逐级返回，不直接退出到聊天主页
    BackHandler(
        enabled = currentScreen != VocabScreen.NONE
    ) {
        when {
            uiState.isReviewMode -> onSetIsReviewMode(false)
            uiState.sessionSummary != null -> {
                onSetSessionSummary("")
                onVocabSubScreenChange(VocabSubScreen.DASHBOARD)
            }
            vocabSubScreen == VocabSubScreen.BOOK_DETAIL -> {
                onVocabSubScreenChange(VocabSubScreen.BOOK_LIST)
            }
            else -> onVocabSubScreenChange(VocabSubScreen.DASHBOARD)
        }
    }

    AnimatedContent(
        targetState = currentScreen,
        transitionSpec = {
            // 根据导航方向决定滑入滑出方向：前进向右进、向左出；回退相反
            val forward = targetState.ordinal > initialState.ordinal
            val (inX, outX) = if (forward) 1 to -1 else -1 to 1
            (slideInHorizontally(tween(300)) { it * inX } + fadeIn(tween(300)))
                .togetherWith(
                    slideOutHorizontally(tween(300)) { it * outX } + fadeOut(tween(300))
                )
        },
        modifier = Modifier
            .fillMaxSize()
            .background(Background)
    ) { screen ->
        when (screen) {
            VocabScreen.REVIEW -> {
                VocabReviewScreen(
                    uiState = uiState,
                    elapsedSeconds = elapsedSeconds,
                    onSetShowAnswer = onSetShowAnswer,
                    onSubmitReview = onSubmitReview,
                    onSetIsReviewMode = onSetIsReviewMode
                )
            }
            VocabScreen.SUMMARY -> {
                VocabSummaryScreen(
                    reviewResults = uiState.reviewResults,
                    isNewWordsMode = uiState.isNewWordsMode,
                    // 复习分组：finishSession 已预取下一组，空组时不再诱导点击
                    hasMore = uiState.isNewWordsMode || uiState.learnWords.isNotEmpty(),
                    onContinue = {
                        onSetSessionSummary("")
                        when {
                            uiState.isNewWordsMode -> onStartNewWords()
                            uiState.learnWords.isNotEmpty() -> onStartReview()
                        }
                    },
                    onExit = {
                        onSetSessionSummary("")
                        onVocabSubScreenChange(VocabSubScreen.DASHBOARD)
                    }
                )
            }
            VocabScreen.BOOK_LIST -> {
                VocabBookListScreen(
                    uiState = uiState,
                    onBack = { onVocabSubScreenChange(VocabSubScreen.DASHBOARD) },
                    onSelectBook = { filename ->
                        // 当前这本再点一次不重复切书，只打开详情
                        if (filename != uiState.currentBook) onSwitchBook(filename)
                        onVocabSubScreenChange(VocabSubScreen.BOOK_DETAIL)
                    }
                )
            }
            VocabScreen.BOOK_DETAIL -> {
                VocabBookDetailScreen(
                    uiState = uiState,
                    onBack = { onVocabSubScreenChange(VocabSubScreen.BOOK_LIST) },
                    onStartNewWords = {
                        onVocabSubScreenChange(VocabSubScreen.DASHBOARD)
                        onStartNewWords()
                    },
                    onLoadBookWords = onLoadBookWords
                )
            }
            VocabScreen.MISTAKES -> {
                VocabMistakesScreen(
                    uiState = uiState,
                    onBack = { onVocabSubScreenChange(VocabSubScreen.DASHBOARD) }
                )
            }
            VocabScreen.NONE -> { /* 不渲染 */ }
        }
    }
}

/** 宿主内部页面枚举（顺序决定整页切换的滑入滑出方向） */
private enum class VocabScreen {
    NONE,        // 未进入词汇模块
    BOOK_LIST,   // 词书列表
    BOOK_DETAIL, // 词书详情
    MISTAKES,    // 错题本
    REVIEW,      // 复习模式
    SUMMARY      // 会话总结
}
