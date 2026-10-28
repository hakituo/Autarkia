package com.aveline.ai.mobile.presentation.study

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.PlanItem
import com.aveline.ai.mobile.presentation.components.AvelineTabRow
import com.aveline.ai.mobile.presentation.components.ModuleHeader
import com.aveline.ai.mobile.presentation.study.today.currentTodayDateLabel
import com.aveline.ai.mobile.presentation.study.today.formatTodayDateLabel
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/**
 * Study 顶层信息架构。
 *
 * 旧枚举项暂时保留给 NavGraph 的按需加载回调使用，但不会出现在 TabRow 中。
 */
enum class StudyTabV2(val title: String) {
    TODAY("今天"),
    SUBJECTS("学科"),
    FOCUS("专注"),
    MORE("更多"),

    // Legacy loading targets — hidden from top-level navigation.
    OVERVIEW("概览"),
    PLAN("计划"),
    DIARY("日记"),
    NOTES("笔记"),
    VOCAB("词汇")
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun StudyScreenV2(
    uiState: StudyUiState,
    dailyUiState: StudyDailyUiState,
    focusState: StudyFocusState,
    planUiState: StudyPlanUiState,
    notesUiState: StudyNotesUiState,
    vocabUiState: VocabUiState,
    /** 当前复习会话累计前台秒数（背单词自动计时，仅前台累加）。 */
    vocabElapsedSeconds: StateFlow<Int>,
    onTabChange: (StudyTabV2) -> Unit,
    onMoreSectionOpen: (StudyMoreSection) -> Unit = {},
    onTopicChange: (String) -> Unit,
    onContentChange: (String) -> Unit,
    onDurationChange: (Int) -> Unit,
    onRecordStudy: () -> Unit,
    onStartStudy: () -> Unit,
    onFinishStudy: () -> Unit,
    onClearError: () -> Unit,
    onStartReview: () -> Unit,
    onStartNewWords: () -> Unit = {},
    onNewWordsBatchSizeChange: (Int) -> Unit = {},
    onReviewBatchSizeChange: (Int) -> Unit = {},
    onSubmitReview: (String) -> Unit,
    onSetShowAnswer: (Boolean) -> Unit,
    onSetIsReviewMode: (Boolean) -> Unit,
    onSetSessionSummary: (String) -> Unit,
    onOpenLibraryNote: (String) -> Unit,
    onCloseLibraryNoteReader: () -> Unit,
    onSelectDate: (String) -> Unit,
    onTogglePlanItem: (PlanItem) -> Unit = {},
    onAddPlanItem: (PlanItem) -> Unit = {},
    onUpdatePlanItem: (PlanItem, PlanItem) -> Unit = { _, _ -> },
    onDeletePlanItem: (PlanItem) -> Unit = {},
    onPlanStartFocus: (PlanItem) -> Unit = {},
    onToggleFocusTimer: () -> Unit = {},
    onResetFocusTimer: () -> Unit = {},
    onSkipFocusPhase: () -> Unit = {},
    onFocusWorkMinutesChange: (Int) -> Unit = {},
    onFocusBreakMinutesChange: (Int) -> Unit = {},
    onFocusLongBreakMinutesChange: (Int) -> Unit = {},
    onFocusNameChange: (String) -> Unit = {},
    onToggleWordOrder: () -> Unit = {},
    onOpenBooks: () -> Unit = {},
    onLoadBookWords: () -> Unit = {},
    onSwitchBook: (String) -> Unit = {},
    onSearch: (String) -> Unit = {},
    onClearSearch: () -> Unit = {},
    /**
     * 深链直达背单词（通知点击）：true 时首屏直接落在「更多 → 词汇」，
     * 而不是停在"今天"概览页 —— 用户点背单词通知就是为了马上背，
     * 落到概览还要再点两次才能开始。
     */
    initialVocab: Boolean = false
) {
    val tabs = remember {
        listOf(
            StudyTabV2.TODAY,
            StudyTabV2.SUBJECTS,
            StudyTabV2.FOCUS,
            StudyTabV2.MORE
        )
    }
    // 直达背单词时首屏翻到「更多」页（TabRow 第 4 项）
    val pagerState = rememberPagerState(
        initialPage = if (initialVocab) tabs.indexOf(StudyTabV2.MORE) else 0
    ) { tabs.size }
    val scope = rememberCoroutineScope()
    var moreSection by remember {
        mutableStateOf(if (initialVocab) StudyMoreSection.VOCAB else StudyMoreSection.HUB)
    }
    var vocabSubScreen by remember { mutableStateOf(VocabSubScreen.DASHBOARD) }
    // 页头右侧日期跟着「今天」走；切到其他 Tab 时不显示，避免和暂存的日期互相矛盾。
    val planDate = planUiState.plan?.date ?: planUiState.selectedDate
    val todayDateLabel = remember(planDate) {
        formatTodayDateLabel(planDate).ifBlank { currentTodayDateLabel() }
    }

    // 以停稳的页为准：点「管理计划」从今天翻到「更多」时会途经学科/专注，
    // 用 currentPage 会在途中把刚打开的计划板块重置回入口，并在滑动中途触发加载。
    LaunchedEffect(pagerState.settledPage) {
        val tab = tabs[pagerState.settledPage]
        onTabChange(tab)
        // Today 依赖 typed DailyPlan；复用 NavGraph 现有 PLAN 加载分支，避免重复网络层逻辑。
        if (tab == StudyTabV2.TODAY) {
            onTabChange(StudyTabV2.PLAN)
        }
        if (tab != StudyTabV2.MORE) {
            moreSection = StudyMoreSection.HUB
            if (!vocabUiState.isReviewMode) {
                vocabSubScreen = VocabSubScreen.DASHBOARD
            }
        }
    }

    fun requestMoreSection(section: StudyMoreSection) {
        moreSection = section
        onMoreSectionOpen(section)
        when (section) {
            StudyMoreSection.PLAN -> onTabChange(StudyTabV2.PLAN)
            StudyMoreSection.VOCAB -> onTabChange(StudyTabV2.VOCAB)
            StudyMoreSection.NOTES -> onTabChange(StudyTabV2.NOTES)
            StudyMoreSection.DIARY -> onTabChange(StudyTabV2.DIARY)
            StudyMoreSection.RECORDS -> onTabChange(StudyTabV2.OVERVIEW)
            StudyMoreSection.HUB -> Unit
        }
    }

    // 深链直达背单词：切页的 LaunchedEffect 只会触发 onTabChange(MORE)（不加载词汇），
    // 这里补一次分区切换，才会真正拉取今日单词/复习总览。
    LaunchedEffect(Unit) {
        if (initialVocab) requestMoreSection(StudyMoreSection.VOCAB)
    }

    // 系统返回键逐级回退：二级板块 → 「更多」入口，而不是直接退出 Study 回到聊天页。
    // 词汇全屏层（StudyVocabBookHost）的 BackHandler 在它之后组合，LIFO 下优先级更高，
    // 所以背单词/词书里按返回仍然是先在词汇内部退一层。
    BackHandler(enabled = moreSection != StudyMoreSection.HUB) {
        moreSection = StudyMoreSection.HUB
        if (!vocabUiState.isReviewMode) {
            vocabSubScreen = VocabSubScreen.DASHBOARD
        }
    }

    fun openMoreSection(section: StudyMoreSection) {
        requestMoreSection(section)
        if (section != StudyMoreSection.VOCAB && !vocabUiState.isReviewMode) {
            vocabSubScreen = VocabSubScreen.DASHBOARD
        }
    }

    // 三层「盖住」：二级板块盖学习页本体；笔记阅读页、词汇全屏层再盖二级板块。
    // 被盖住的一层只左移让位并压暗，盖上来的一层从右侧推入，全程只有一个方向在动。
    val moreCover = rememberLayerCover(
        covered = moreSection != StudyMoreSection.HUB,
        label = "study_more_cover"
    )
    val readerCover = rememberLayerCover(
        covered = notesUiState.isReaderOpen,
        label = "study_reader_cover"
    )
    val vocabCover = rememberVocabBaseCover(resolveVocabScreen(vocabUiState, vocabSubScreen))

    Box(modifier = Modifier.fillMaxSize()) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .then(with(vocabCover) { Modifier.basePose() })
                .then(with(readerCover) { Modifier.basePose() })
        ) {
            Column(
                modifier = with(moreCover) {
                    Modifier
                        .fillMaxSize()
                        .basePose()
                        .statusBarsPadding()
                }
            ) {
                // 页头与 Tab 栏常驻：二级板块从上层盖过来，这里不收起、不跳动
                // 不再放刷新键：回到页面时由 ON_RESUME 的变更检查自动刷新
                // 页头只留「学习」：Tab 自己就是标题，正文里不再重复写「今天 / 学科 / 更多」。
                // 「今天」页把日期放在右侧，其他页留空，页头宽度不跳。
                ModuleHeader(
                    title = "学习",
                    actions = {
                        if (tabs[pagerState.currentPage] == StudyTabV2.TODAY &&
                            todayDateLabel.isNotBlank()
                        ) {
                            // 贴住「学习」的行底：日期是页头的副信息，不跟标题抢中线。
                            Box(
                                modifier = Modifier.height(38.dp),
                                contentAlignment = Alignment.BottomEnd
                            ) {
                                Text(
                                    text = todayDateLabel,
                                    fontSize = 13.sp,
                                    color = TextTertiary
                                )
                            }
                        }
                    }
                )

                AvelineTabRow(
                    titles = tabs.map { it.title },
                    selectedTabIndex = pagerState.currentPage,
                    onTabSelected = { index ->
                        scope.launch { pagerState.animateScrollToPage(index) }
                    },
                    modifier = Modifier.fillMaxWidth()
                )
        

                // 「更多」进入二级板块（计划/词汇/笔记/日记/学习记录）后禁用外层手势：
                // 否则子页面里的横向滑动会被外层 pager 吃掉，把整个“更多”页翻到左边的「专注」。
                // 注意只禁用手势，TabRow 点击走 animateScrollToPage 的程序化切页不受影响。
                val pagerGestureEnabled = moreSection == StudyMoreSection.HUB

                // 16dp 边距放进每一页里而不是套在分页器外：切页时内容一直滑到屏幕边缘，
                // 不会在离边 16dp 处被硬切。
                HorizontalPager(
                    state = pagerState,
                    userScrollEnabled = pagerGestureEnabled,
                    modifier = Modifier.fillMaxSize()
                ) { page ->
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(horizontal = 16.dp),
                        contentAlignment = Alignment.TopStart
                    ) {
                        when (tabs[page]) {
                            StudyTabV2.TODAY -> StudyTodayTab(
                                uiState = uiState,
                                planUiState = planUiState,
                                onToggleItem = onTogglePlanItem,
                                onStartFocus = { item ->
                                    StudyPlanFocusLink.select(item.id)
                                    onPlanStartFocus(item)
                                    scope.launch { pagerState.animateScrollToPage(StudyTabV2.FOCUS.ordinal) }
                                },
                                onOpenPlanManager = {
                                    requestMoreSection(StudyMoreSection.PLAN)
                                    scope.launch { pagerState.animateScrollToPage(StudyTabV2.MORE.ordinal) }
                                }
                            )

                            StudyTabV2.SUBJECTS -> StudySubjectsTab(dailyUiState = dailyUiState)

                            StudyTabV2.FOCUS -> StudyFocusTab(
                                focusState = focusState,
                                onToggleTimer = onToggleFocusTimer,
                                onReset = onResetFocusTimer,
                                onSkipPhase = onSkipFocusPhase,
                                onWorkMinutesChange = onFocusWorkMinutesChange,
                                onBreakMinutesChange = onFocusBreakMinutesChange,
                                onLongBreakMinutesChange = onFocusLongBreakMinutesChange,
                                onFocusNameChange = onFocusNameChange
                            )

                            StudyTabV2.MORE -> StudyMoreHub(onOpen = ::openMoreSection)

                            else -> Unit
                        }
                    }
                }
            }

            moreCover.ScrimLayer()
            StudyMoreSectionLayer(
                section = moreSection,
                uiState = uiState,
                dailyUiState = dailyUiState,
                planUiState = planUiState,
                notesUiState = notesUiState,
                vocabUiState = vocabUiState,
                onSectionChange = ::openMoreSection,
                onDateSelected = onSelectDate,
                onTogglePlanItem = onTogglePlanItem,
                onAddPlanItem = onAddPlanItem,
                onUpdatePlanItem = onUpdatePlanItem,
                onDeletePlanItem = onDeletePlanItem,
                onPlanStartFocus = { item ->
                    StudyPlanFocusLink.select(item.id)
                    onPlanStartFocus(item)
                    scope.launch { pagerState.animateScrollToPage(StudyTabV2.FOCUS.ordinal) }
                },
                onTopicChange = onTopicChange,
                onContentChange = onContentChange,
                onDurationChange = onDurationChange,
                onRecordStudy = onRecordStudy,
                onStartStudy = onStartStudy,
                onFinishStudy = onFinishStudy,
                onStartReview = onStartReview,
                onStartNewWords = onStartNewWords,
                onNewWordsBatchSizeChange = onNewWordsBatchSizeChange,
                onReviewBatchSizeChange = onReviewBatchSizeChange,
                onToggleWordOrder = onToggleWordOrder,
                onOpenBooks = {
                    onOpenBooks()
                    vocabSubScreen = VocabSubScreen.BOOK_LIST
                },
                onOpenMistakes = { vocabSubScreen = VocabSubScreen.MISTAKES },
                onSearch = onSearch,
                onClearSearch = onClearSearch,
                onOpenLibraryNote = onOpenLibraryNote
            )
        }

        // 笔记阅读页挂在根层：列表在二级板块里、左右各有 16dp 内边距，放在列表里会被切窄。
        readerCover.ScrimLayer()
        AnimatedVisibility(
            visible = notesUiState.isReaderOpen,
            enter = vocabTransform(VocabMove.PushForward).targetContentEnter,
            exit = vocabTransform(VocabMove.PushBack).initialContentExit
        ) {
            VocabPage(move = if (notesUiState.isReaderOpen) VocabMove.PushForward else VocabMove.PushBack) {
                NoteReaderScreen(uiState = notesUiState, onClose = onCloseLibraryNoteReader)
            }
        }

        // 词汇全屏层盖住学习页时，本体跟着让位（推入左移 / 会话缩小），再压一层遮罩
        vocabCover.ScrimLayer()
        StudyVocabBookHost(
            uiState = vocabUiState,
            elapsedSeconds = vocabElapsedSeconds,
            vocabSubScreen = vocabSubScreen,
            onVocabSubScreenChange = { vocabSubScreen = it },
            onSetShowAnswer = onSetShowAnswer,
            onSubmitReview = onSubmitReview,
            onSetIsReviewMode = onSetIsReviewMode,
            onSetSessionSummary = onSetSessionSummary,
            onSwitchBook = onSwitchBook,
            onLoadBookWords = onLoadBookWords,
            onStartNewWords = onStartNewWords,
            onStartReview = onStartReview
        )

        // 轻提示在最上层：背词会话里出错（如提交失败、没有新词）也看得到
        StudyToast(
            error = uiState.error,
            success = uiState.successMessage,
            onDismiss = onClearError,
            modifier = Modifier.align(Alignment.TopCenter)
        )
    }
}
