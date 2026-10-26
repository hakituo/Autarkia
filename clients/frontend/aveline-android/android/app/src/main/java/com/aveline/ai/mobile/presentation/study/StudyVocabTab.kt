package com.aveline.ai.mobile.presentation.study

import androidx.compose.runtime.Composable
import com.aveline.ai.mobile.presentation.study.vocab.VocabHomeScreen

/**
 * 词汇 Tab 入口（薄壳）。
 *
 * 页面结构与交互在 `presentation/study/vocab/VocabHomeScreen.kt`，
 * 这里只做参数转发，避免学习页入口继续膨胀。
 */
@Composable
fun StudyVocabTab(
    uiState: VocabUiState,
    onStartReview: () -> Unit,
    onStartNewWords: () -> Unit = {},
    onToggleOrder: () -> Unit = {},
    onAddManualStudy: (Int) -> Unit = {},
    onOpenBooks: () -> Unit = {},
    onOpenMistakes: () -> Unit = {},
    onSearch: (String) -> Unit = {},
    onClearSearch: () -> Unit = {},
    onNewWordsBatchSizeChange: (Int) -> Unit = {},
    onReviewBatchSizeChange: (Int) -> Unit = {}
) {
    VocabHomeScreen(
        uiState = uiState,
        onStartReview = onStartReview,
        onStartNewWords = onStartNewWords,
        onToggleOrder = onToggleOrder,
        onAddManualStudy = onAddManualStudy,
        onOpenBooks = onOpenBooks,
        onOpenMistakes = onOpenMistakes,
        onSearch = onSearch,
        onClearSearch = onClearSearch,
        onNewWordsBatchSizeChange = onNewWordsBatchSizeChange,
        onReviewBatchSizeChange = onReviewBatchSizeChange
    )
}
