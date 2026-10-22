package com.aveline.ai.mobile.presentation.navigation.graph

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavType
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import androidx.navigation.navDeepLink
import com.aveline.ai.mobile.presentation.navigation.NavArgs
import com.aveline.ai.mobile.presentation.navigation.Routes
import com.aveline.ai.mobile.presentation.navigation.fadeEnter
import com.aveline.ai.mobile.presentation.navigation.fadeExit
import com.aveline.ai.mobile.presentation.study.StudyDailyViewModel
import com.aveline.ai.mobile.presentation.study.StudyFocusViewModel
import com.aveline.ai.mobile.presentation.study.StudyNotesViewModel
import com.aveline.ai.mobile.presentation.study.StudyPlanViewModel
import com.aveline.ai.mobile.presentation.study.StudyScreenV2
import com.aveline.ai.mobile.presentation.study.StudyTabV2
import com.aveline.ai.mobile.presentation.study.StudyViewModel
import com.aveline.ai.mobile.presentation.study.parseDurationMinutes
import kotlinx.coroutines.flow.collectLatest

/** 学习页（概览 / 计划 / 日记 / 笔记 / 文件 / 词汇）。 */
internal fun NavGraphBuilder.studyScreen() {
    composable(
        route = "${Routes.STUDY}?${NavArgs.TAB}={${NavArgs.TAB}}",
        arguments = listOf(
            navArgument(NavArgs.TAB) {
                type = NavType.StringType
                nullable = true
                defaultValue = null
            }
        ),
        deepLinks = listOf(
            navDeepLink { uriPattern = "aveline://study" },
            // 背单词通知深链：tab=vocab 直达「更多 → 词汇」，
            // 不带参数时停在概览页（概览是学习主页，不该被通知改写默认入口）。
            navDeepLink { uriPattern = "aveline://study?tab={${NavArgs.TAB}}" }
        ),
        enterTransition = fadeEnter,
        exitTransition = fadeExit,
        popEnterTransition = fadeEnter,
        popExitTransition = fadeExit
    ) { backStackEntry ->
        val viewModel: StudyViewModel = hiltViewModel()
        val dailyViewModel: StudyDailyViewModel = hiltViewModel()
        val focusViewModel: StudyFocusViewModel = hiltViewModel()
        val planViewModel: StudyPlanViewModel = hiltViewModel()
        val notesViewModel: StudyNotesViewModel = hiltViewModel()
        val uiState by viewModel.uiState.collectAsStateWithLifecycle()
        val dailyUiState by dailyViewModel.uiState.collectAsStateWithLifecycle()
        val focusState by focusViewModel.uiState.collectAsStateWithLifecycle()
        val planUiState by planViewModel.uiState.collectAsStateWithLifecycle()
        val notesUiState by notesViewModel.uiState.collectAsStateWithLifecycle()
        val vocabUiState by viewModel.vocabUiState.collectAsStateWithLifecycle()

        // 深链 tab=vocab（背单词通知）→ 首屏直接落到词汇页
        val initialVocab = backStackEntry.arguments?.getString(NavArgs.TAB) == NavArgs.TAB_VOCAB

        // 回到学习页时先做变更检查：Daily 指纹没变就不重拉日历/笔记，
        // 笔记列表也只在内容真的变了时才更新，避免每次进来都闪一遍。
        val studyLifecycleOwner = LocalLifecycleOwner.current
        DisposableEffect(studyLifecycleOwner) {
            val observer = LifecycleEventObserver { _, event ->
                if (event == Lifecycle.Event.ON_RESUME) {
                    dailyViewModel.checkForChanges()
                    notesViewModel.refreshIfLoaded()
                }
            }
            studyLifecycleOwner.lifecycle.addObserver(observer)
            onDispose { studyLifecycleOwner.lifecycle.removeObserver(observer) }
        }

        // 背单词前台计时：只有学习页处于前台（ON_START..ON_STOP）时才累加，
        // 切后台 / 切到别的 Tab 立即暂停，后台时间不计入学习时长。
        DisposableEffect(studyLifecycleOwner) {
            val observer = LifecycleEventObserver { _, event ->
                when (event) {
                    Lifecycle.Event.ON_START -> viewModel.onVocabSessionForeground()
                    Lifecycle.Event.ON_STOP -> viewModel.onVocabSessionBackground()
                    else -> Unit
                }
            }
            studyLifecycleOwner.lifecycle.addObserver(observer)
            onDispose {
                studyLifecycleOwner.lifecycle.removeObserver(observer)
                viewModel.onVocabSessionBackground()
            }
        }

        // 学习时长落库后刷新今日计划：词汇任务卡要显示实际用时而不是预计时长。
        LaunchedEffect(Unit) {
            viewModel.studyTimeEvents.collectLatest {
                planViewModel.loadPlan(planViewModel.uiState.value.selectedDate)
            }
        }

        Surface(modifier = Modifier.fillMaxSize(), color = Color.Transparent) {
            StudyScreenV2(
                initialVocab = initialVocab,
                uiState = uiState,
                dailyUiState = dailyUiState,
                focusState = focusState,
                planUiState = planUiState,
                notesUiState = notesUiState,
                vocabUiState = vocabUiState,
                vocabElapsedSeconds = viewModel.vocabElapsedSeconds,
                onPlanStartFocus = { planItem ->
                    focusViewModel.setFocusName(planItem.content)
                    parseDurationMinutes(planItem.duration)?.let { minutes ->
                        focusViewModel.setWorkMinutes(minutes)
                    }
                },
                // Tab 切换:根据 tab 触发对应数据加载,不再依赖硬编码数据
                onTabChange = { tab ->
                    when (tab) {
                        StudyTabV2.VOCAB -> {
                            viewModel.loadLearnWords()
                            viewModel.loadManualStudyToday()
                            viewModel.loadVocabBooks()
                            // 拉取复习总览(连续天数+记忆曲线)、今日已背与词书进度
                            viewModel.loadReviewOverview()
                            viewModel.loadMistakes()
                            viewModel.loadVocabInsights()
                        }
                        StudyTabV2.NOTES -> notesViewModel.loadLibraryNotes()
                        StudyTabV2.PLAN -> planViewModel.loadPlan(
                            planViewModel.uiState.value.selectedDate
                        )
                        StudyTabV2.DIARY -> dailyViewModel.loadDateContent(
                            dailyViewModel.uiState.value.selectedDate
                        )
                        else -> {}
                    }
                },
                onTopicChange = viewModel::setRecordTopic,
                onContentChange = viewModel::setRecordContent,
                // 时长:Int -> String
                onDurationChange = { duration ->
                    viewModel.setRecordDuration(duration.toString())
                },
                onRecordStudy = viewModel::recordStudyProgress,
                onStartStudy = viewModel::startStudySession,
                onFinishStudy = viewModel::finishStudySession,
                onClearError = viewModel::clearError,
                onStartReview = viewModel::startReview,
                onStartNewWords = viewModel::startNewWords,
                onNewWordsBatchSizeChange = viewModel::setNewWordsBatchSize,
                onReviewBatchSizeChange = viewModel::setReviewBatchSize,
                // 评分:String -> Int("1".."4" 映射到 1..4)
                onSubmitReview = { quality ->
                    viewModel.submitReview(quality.toIntOrNull() ?: 3)
                },
                onSetShowAnswer = viewModel::setShowAnswer,
                onSetIsReviewMode = viewModel::setIsReviewMode,
                // 会话总结:空字符串 -> null(清除总结)
                onSetSessionSummary = { summary ->
                    viewModel.setSessionSummary(if (summary.isBlank()) null else summary)
                },
                // 学习库笔记:打开/关闭阅读页
                onOpenLibraryNote = { path -> notesViewModel.openNote(path) },
                onCloseLibraryNoteReader = { notesViewModel.closeReader() },
                onSelectDate = { date ->
                    dailyViewModel.selectDate(date)
                    planViewModel.loadPlan(date)
                },
                // 计划项写入全部走计划真源,避免被后端计划同步覆盖
                onTogglePlanItem = { item ->
                    planViewModel.toggleItemDone(
                        planViewModel.uiState.value.selectedDate, item
                    )
                },
                onAddPlanItem = { item ->
                    planViewModel.addItem(
                        planViewModel.uiState.value.selectedDate,
                        item.time,
                        item.content,
                        item.duration
                    )
                },
                onUpdatePlanItem = { original, edited ->
                    planViewModel.updateItem(
                        planViewModel.uiState.value.selectedDate,
                        original,
                        edited.time,
                        edited.content,
                        edited.duration
                    )
                },
                onDeletePlanItem = { item ->
                    planViewModel.removeItem(
                        planViewModel.uiState.value.selectedDate, item
                    )
                },
                // 番茄钟回调（来自独立的 StudyFocusViewModel）
                onToggleFocusTimer = focusViewModel::toggleTimer,
                onResetFocusTimer = focusViewModel::resetTimer,
                onSkipFocusPhase = focusViewModel::skipPhase,
                onFocusWorkMinutesChange = focusViewModel::setWorkMinutes,
                onFocusBreakMinutesChange = focusViewModel::setBreakMinutes,
                onFocusLongBreakMinutesChange = focusViewModel::setLongBreakMinutes,
                onFocusNameChange = focusViewModel::setFocusName,
                onToggleWordOrder = viewModel::toggleWordOrder,
                onAddManualStudy = viewModel::addManualStudy,
                onOpenBooks = viewModel::loadVocabBooks,
                onLoadBookWords = { viewModel.loadBookWords() },
                onSwitchBook = viewModel::switchVocabBook,
                onSearch = viewModel::searchDictionary,
                onClearSearch = viewModel::clearSearch
            )
        }
    }
}
