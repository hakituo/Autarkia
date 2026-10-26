package com.aveline.ai.mobile.presentation.companion

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.AIModel
import com.aveline.ai.mobile.domain.models.Memory
import com.aveline.ai.mobile.domain.models.MemorySortOrder
import com.aveline.ai.mobile.presentation.components.AvelineTabRow
import com.aveline.ai.mobile.presentation.memory.MemoryGraphUiState
import com.aveline.ai.mobile.presentation.memory.MemoryUiState
import com.aveline.ai.mobile.presentation.persona.PersonaUiState
import com.aveline.ai.mobile.presentation.status.ui.StatusUiState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/**
 * Companion 主界面。
 *
 * 合并状态 / 日程 / 模型 / 人设 / 记忆五个页面,使用 TabRow + HorizontalPager 切换。
 *
 * 右滑关闭由外层 PullableDismissPanel 统一处理；Pager 在第 0 页到达边界后，
 * 通过 NestedScroll 把未消费位移交给外层，不在本页面注册全屏 pointerInput。
 *
 * @param statusUiState 状态页 UI 状态
 * @param clockFlow 当前时钟流（单独传，只在状态卡片内部订阅，避免每秒整棵面板重组）
 * @param personaUiState 人设页 UI 状态
 * @param memoryUiState 记忆页 UI 状态
 * @param availableModels 模型页可用模型列表
 * @param selectedModel 模型页当前选中模型
 * @param modelLoading 模型列表加载中
 * @param modelError 模型列表加载错误
 * @param onModelSelected 选中模型回调（传模型 id）
 * @param onRefreshStatus 刷新状态回调
 * @param onSwitchPersona 切换人设回调（仅在当前角色范围内切换）
 * @param onSearchMemory 搜索记忆回调
 * @param onMemoryTopicFilterChange 记忆话题过滤回调
 * @param onToggleImportantOnly 切换只看重要回调
 * @param onMemorySortOrderChange 记忆排序回调
 * @param onDeleteMemory 删除记忆回调
 * @param onToggleImportant 切换重要标记回调
 * @param onConfirmDeleteMemory 确认删除回调
 * @param onCancelDeleteMemory 取消删除回调
 * @param onClearMemoryFilters 清除记忆过滤回调
 * @param onOpenMemoryDetail 打开记忆详情回调
 * @param onCloseMemoryDetail 关闭记忆详情回调
 * @param graphUiState 记忆网络（地标 / 邻域 / 关联）状态
 * @param onGraphEnter 进入记忆网络时加载地标
 * @param onGraphAnchorClick 展开某个地标
 * @param onGraphBack 退回地标层
 * @param onGraphRetry 记忆网络加载失败重试
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun CompanionScreen(
    statusUiState: StatusUiState,
    clockFlow: StateFlow<String>,
    personaUiState: PersonaUiState,
    memoryUiState: MemoryUiState,
    graphUiState: MemoryGraphUiState,
    availableModels: List<AIModel>,
    selectedModel: AIModel?,
    modelLoading: Boolean = false,
    modelError: String? = null,
    onModelSelected: (String) -> Unit,
    viewingFilename: String? = null,
    /** 手选音色：(persona filename, 音色名)。 */
    onSelectVoice: (String, String) -> Unit = { _, _ -> },
    /** 恢复跟随角色默认音色：(persona filename)。 */
    onResetVoice: (String) -> Unit = {},
    onRefreshStatus: () -> Unit,
    onSilentRefreshStatus: () -> Unit = {},
    onWakeCompanion: () -> Unit,
    onInterruptCompanion: () -> Unit,
    onSkipCompanionActivity: () -> Unit,
    onDismissGestureEnabledChange: (Boolean) -> Unit,
    onSwitchPersona: (String) -> Unit,
    onSearchMemory: (String) -> Unit,
    onMemoryTopicFilterChange: (String?) -> Unit,
    onToggleImportantOnly: () -> Unit,
    onMemorySortOrderChange: (MemorySortOrder) -> Unit,
    onDeleteMemory: (Memory) -> Unit,
    onToggleImportant: (Memory) -> Unit,
    onConfirmDeleteMemory: () -> Unit,
    onCancelDeleteMemory: () -> Unit,
    onClearMemoryFilters: () -> Unit,
    onOpenMemoryDetail: (Memory) -> Unit,
    onCloseMemoryDetail: () -> Unit,
    onGraphEnter: () -> Unit,
    onGraphAnchorClick: (String) -> Unit,
    onGraphBack: () -> Unit,
    onGraphRetry: () -> Unit
) {
    // 五个 tab：日程紧邻状态，始终展示当前聊天角色当天的计划。
    val tabs = remember { listOf("状态", "日程", "模型", "人设", "记忆") }
    val pagerState = rememberPagerState(initialPage = 0) { tabs.size }
    val scope = rememberCoroutineScope()

    // 一次手势只能做一层导航：从其他页右滑只交给 Pager。
    // 必须先松手稳定在"状态"，下一次新右滑才允许外层详情面板退出。
    //
    // 只以 settledPage 为 key：滑动过程中"是否正在滑动"这个状态会反复翻转，
    // 把 effect 打断重启；松手瞬间才确定停在哪一页，此时才触发一次静默刷新，
    // 避免滑动过程中反复发请求导致掉帧。
    LaunchedEffect(pagerState.settledPage) {
        onDismissGestureEnabledChange(pagerState.settledPage == 0)
        if (pagerState.settledPage == 1) onSilentRefreshStatus()
    }

    Column(
        modifier = Modifier.fillMaxSize()
    ) {
        CompanionTabRow(
            tabs = tabs,
            pagerState = pagerState,
            scope = scope
        )

        // Tab 内容区域:使用 HorizontalPager 实现左右滑动切换
        HorizontalPager(
            state = pagerState,
            // 预组合相邻页：滑动时不必临时组合重内容，避免滑动中掉帧
            beyondViewportPageCount = 1,
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 16.dp)
        ) { page ->
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.TopStart
            ) {
                when (page) {
                    0 -> CompanionStatusTab(
                        uiState = statusUiState,
                        clockFlow = clockFlow,
                        onRefresh = onRefreshStatus,
                        onWake = onWakeCompanion,
                        onInterrupt = onInterruptCompanion,
                        onSkip = onSkipCompanionActivity
                    )
                    1 -> CompanionScheduleTab(uiState = statusUiState)
                    2 -> CompanionModelTab(
                        availableModels = availableModels,
                        selectedModel = selectedModel,
                        isLoading = modelLoading,
                        error = modelError,
                        onModelSelected = onModelSelected
                    )
                    3 -> CompanionPersonaTab(
                        uiState = personaUiState,
                        viewingFilename = viewingFilename,
                        onSwitchPersona = onSwitchPersona,
                        onSelectVoice = onSelectVoice,
                        onResetVoice = onResetVoice
                    )
                    4 -> CompanionMemoryTab(
                        uiState = memoryUiState,
                        onSearch = onSearchMemory,
                        onTopicFilterChange = onMemoryTopicFilterChange,
                        onToggleImportantOnly = onToggleImportantOnly,
                        onSortOrderChange = onMemorySortOrderChange,
                        onDeleteMemory = onDeleteMemory,
                        onToggleImportant = onToggleImportant,
                        onConfirmDelete = onConfirmDeleteMemory,
                        onCancelDelete = onCancelDeleteMemory,
                        onClearFilters = onClearMemoryFilters,
                        onMemoryClick = onOpenMemoryDetail,
                        onCloseDetail = onCloseMemoryDetail,
                        graphUiState = graphUiState,
                        onGraphEnter = onGraphEnter,
                        onGraphAnchorClick = onGraphAnchorClick,
                        onGraphBack = onGraphBack,
                        onGraphRetry = onGraphRetry
                    )
                }
            }
        }
    }
}

/**
 * Tab 栏。
 *
 * `pagerState.currentPage` 只在**这一层**读取：滑动经过页面中点时它会变一次，
 * 如果在上面的 [CompanionScreen] 里读，整屏（Pager + 五个页面的内容）都会跟着重组，
 * 长列表页（模型选择）会因此明显掉帧。
 */
@Composable
private fun CompanionTabRow(
    tabs: List<String>,
    pagerState: PagerState,
    scope: CoroutineScope
) {
    AvelineTabRow(
        titles = tabs,
        selectedTabIndex = pagerState.currentPage,
        onTabSelected = { index ->
            scope.launch { pagerState.animateScrollToPage(index) }
        },
        modifier = Modifier.fillMaxWidth()
    )
}
