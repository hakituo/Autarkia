package com.aveline.ai.mobile.presentation.study

import androidx.compose.animation.AnimatedContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.PlanItem
import com.aveline.ai.mobile.presentation.components.controls.AvelineIconButton
import com.aveline.ai.mobile.presentation.study.vocab.VocabHomeScreen
import com.aveline.ai.mobile.presentation.study.vocab.VocabSettingsSheet
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Study 顶层“更多”里的功能入口。 */
enum class StudyMoreSection(val title: String) {
    HUB("更多"),
    PLAN("计划"),
    VOCAB("词汇"),
    NOTES("笔记"),
    DIARY("日记"),
    RECORDS("学习记录")
}

/**
 * 「更多」的二级板块层（计划 / 词汇 / 笔记 / 日记 / 学习记录）。
 *
 * 挂在学习页根层、盖在页头和分页器之上：进入时板块从右侧整屏推入，
 * 下面的学习页原地不动，只左移让位并压暗（由 [rememberLayerCover] 驱动）。
 * 入口列表本身在分页器的「更多」页里，这一层在 [StudyMoreSection.HUB] 时留空、不拦截点击。
 */
@Composable
fun StudyMoreSectionLayer(
    section: StudyMoreSection,
    uiState: StudyUiState,
    dailyUiState: StudyDailyUiState,
    planUiState: StudyPlanUiState,
    notesUiState: StudyNotesUiState,
    vocabUiState: VocabUiState,
    onSectionChange: (StudyMoreSection) -> Unit,
    onDateSelected: (String) -> Unit,
    onTogglePlanItem: (PlanItem) -> Unit,
    onAddPlanItem: (PlanItem) -> Unit,
    onUpdatePlanItem: (PlanItem, PlanItem) -> Unit,
    onDeletePlanItem: (PlanItem) -> Unit,
    onPlanStartFocus: (PlanItem) -> Unit,
    onTopicChange: (String) -> Unit,
    onContentChange: (String) -> Unit,
    onDurationChange: (Int) -> Unit,
    onRecordStudy: () -> Unit,
    onStartStudy: () -> Unit,
    onFinishStudy: () -> Unit,
    onStartReview: () -> Unit,
    onStartNewWords: () -> Unit,
    onNewWordsBatchSizeChange: (Int) -> Unit = {},
    onReviewBatchSizeChange: (Int) -> Unit = {},
    onToggleWordOrder: () -> Unit,
    onOpenBooks: () -> Unit,
    onOpenMistakes: () -> Unit,
    onSearch: (String) -> Unit,
    onClearSearch: () -> Unit,
    onOpenLibraryNote: (String) -> Unit,
    modifier: Modifier = Modifier
) {
    var showVocabSettings by remember { mutableStateOf(false) }

    val move = if (section == StudyMoreSection.HUB) VocabMove.PushBack else VocabMove.PushForward

    // 只有水平一个方向在动：板块推入 / 推出，学习页页头和 Tab 栏不收起、不跳动
    AnimatedContent(
        targetState = section,
        transitionSpec = {
            vocabTransform(
                if (targetState == StudyMoreSection.HUB) VocabMove.PushBack else VocabMove.PushForward
            )
        },
        modifier = modifier.fillMaxSize(),
        label = "study_more_section"
    ) { current ->
        if (current == StudyMoreSection.HUB) {
            Box(modifier = Modifier.fillMaxSize())
            return@AnimatedContent
        }
        VocabPage(move = move) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .statusBarsPadding()
                    .padding(horizontal = 16.dp)
            ) {
                val noteTree = notesUiState.noteTree
                val noteCount = remember(noteTree) { noteTree.sumOf { it.fileCount() } }
                val noteSubtitle = when {
                    noteTree.isNotEmpty() -> "$noteCount 篇 · ${noteTree.size} 个科目"
                    notesUiState.isLoading -> "正在加载笔记…"
                    else -> "暂无笔记"
                }
                val diaryDate = dailyUiState.selectedDate.ifBlank {
                    SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())
                }

                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        // 二级板块统一吞掉横向滑动：默认不让横滑冒泡到顶层把全局侧边栏拖出来。
                        // 有"上一个 / 下一个"概念的板块（计划 / 日记）在更内层自己接住横滑翻日期，
                        // 更内层的手势先拿到事件，因此不会被这里抢走。
                        .consumeHorizontalSwipe()
                ) {
                    MoreSectionHeader(
                        title = current.title,
                        subtitle = if (current == StudyMoreSection.NOTES) noteSubtitle else null,
                        onBack = { onSectionChange(StudyMoreSection.HUB) },
                        trailing = {
                            if (current == StudyMoreSection.VOCAB) {
                                AvelineIconButton(
                                    icon = Icons.Outlined.Settings,
                                    contentDescription = "背词设置",
                                    onClick = { showVocabSettings = true }
                                )
                            }
                            if (current == StudyMoreSection.DIARY) {
                                DiaryDateNav(
                                    date = diaryDate,
                                    onPrevious = { onDateSelected(shiftDateString(diaryDate, -1)) },
                                    onNext = { onDateSelected(shiftDateString(diaryDate, 1)) }
                                )
                            }
                        }
                    )

                    when (current) {
                        StudyMoreSection.PLAN -> StudyPlanTab(
                            planUiState = planUiState,
                            onDateSelected = onDateSelected,
                            onToggleItem = onTogglePlanItem,
                            onAddItem = onAddPlanItem,
                            onUpdateItem = onUpdatePlanItem,
                            onDeleteItem = onDeletePlanItem,
                            onStartFocus = onPlanStartFocus
                        )

                        StudyMoreSection.VOCAB -> LazyColumn(
                            modifier = Modifier.fillMaxWidth(),
                            contentPadding = PaddingValues(top = 18.dp, bottom = 28.dp),
                            verticalArrangement = Arrangement.spacedBy(16.dp)
                        ) {
                            item {
                                VocabHomeScreen(
                                    uiState = vocabUiState,
                                    onStartReview = onStartReview,
                                    onStartNewWords = onStartNewWords,
                                    onOpenBooks = onOpenBooks,
                                    onOpenMistakes = onOpenMistakes,
                                    onSearch = onSearch,
                                    onClearSearch = onClearSearch
                                )
                            }
                        }

                        StudyMoreSection.NOTES -> StudyNotesTab(
                            notesUiState = notesUiState,
                            onOpenNote = onOpenLibraryNote
                        )

                        StudyMoreSection.DIARY -> StudyDiaryTab(
                            dailyUiState = dailyUiState,
                            onDateSelected = onDateSelected
                        )

                        StudyMoreSection.RECORDS -> StudyOverviewTab(
                            uiState = uiState,
                            dailyUiState = dailyUiState,
                            onTopicChange = onTopicChange,
                            onContentChange = onContentChange,
                            onDurationChange = onDurationChange,
                            onRecordStudy = onRecordStudy,
                            onStartStudy = onStartStudy,
                            onFinishStudy = onFinishStudy
                        )

                        StudyMoreSection.HUB -> Unit
                    }
                }
            }
        }
    }

    if (showVocabSettings) {
        VocabSettingsSheet(
            isShuffle = vocabUiState.wordOrder == "shuffle",
            newWordsBatchSize = vocabUiState.newWordsBatchSize,
            reviewBatchSize = vocabUiState.reviewBatchSize,
            onToggleOrder = onToggleWordOrder,
            onNewWordsBatchSizeChange = onNewWordsBatchSizeChange,
            onReviewBatchSizeChange = onReviewBatchSizeChange,
            onDismiss = { showVocabSettings = false }
        )
    }
}
