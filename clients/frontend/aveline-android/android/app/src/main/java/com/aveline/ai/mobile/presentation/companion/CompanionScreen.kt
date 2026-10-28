package com.aveline.ai.mobile.presentation.companion

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.AIModel
import com.aveline.ai.mobile.domain.models.Memory
import com.aveline.ai.mobile.domain.models.MemorySortOrder
import com.aveline.ai.mobile.presentation.memory.MemoryGraphUiState
import com.aveline.ai.mobile.presentation.memory.MemoryUiState
import com.aveline.ai.mobile.presentation.persona.PersonaUiState
import com.aveline.ai.mobile.presentation.status.ui.StatusUiState
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/** Tab 之间的水平间距（设计稿 22dp） */
private val TabGap = 22.dp

/**
 * Companion 主界面。
 *
 * 结构是「页头 + Tab 栏 + Pager」：页头放伴侣本人（名字 / 此刻在做什么 / 会不会回），
 * 五个 Tab 只放各自的内容，不再各自带一张「此刻」卡片。
 *
 * 右滑关闭由外层 PullableDismissPanel 统一处理；Pager 在第 0 页到达边界后，
 * 通过 NestedScroll 把未消费位移交给外层，不在本页面注册全屏 pointerInput。
 *
 * @param companionName 伴侣展示名（页头标题）
 * @param statusUiState 状态页 UI 状态
 * @param clockFlow 当前时钟流（单独传，只在连接行内部订阅，避免每秒整棵面板重组）
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
 * @param onLoadMoreMemory 滚动到底部加载下一页记忆回调
 * @param onOpenMemoryDetail 打开记忆详情回调
 * @param onCloseMemoryDetail 关闭记忆详情回调
 * @param graphUiState 记忆网络（地标 / 邻域 / 关联）状态
 * @param onGraphEnter 进入记忆网络时加载地标
 * @param onGraphAnchorClick 展开某个地标 / 以某条记忆为中心重画
 * @param onGraphBack 退回地标层
 * @param onGraphRetry 记忆网络加载失败重试
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun CompanionScreen(
    companionName: String,
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
    /** 思考模式：null = 该角色没设置过，跟随后端配置（模型页按开显示）。 */
    thinkingEnabled: Boolean? = null,
    onThinkingChange: (Boolean) -> Unit = {},
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
    onLoadMoreMemory: () -> Unit,
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

    Column(modifier = Modifier.fillMaxSize()) {
        // 页头高度固定，不随当前 Tab 变化：翻页时上半屏保持不动
        CompanionHeader(
            name = companionName,
            lifeStatus = statusUiState.lifeStatus,
            actionsEnabled = !statusUiState.isActionRunning,
            actionMessage = statusUiState.actionMessage,
            onWake = onWakeCompanion,
            onInterrupt = onInterruptCompanion,
            onSkip = onSkipCompanionActivity
        )

        CompanionTabRow(
            tabs = tabs,
            pagerState = pagerState,
            scope = scope
        )

        // Tab 内容区域:使用 HorizontalPager 实现左右滑动切换。
        // 左右留白交给各 Tab 自己（页头与 Tab 栏用同一个 CompanionGutter），
        // 这里再加一层 padding 会让三个层级各自内缩，竖线对不齐。
        HorizontalPager(
            state = pagerState,
            // 预组合相邻页：滑动时不必临时组合重内容，避免滑动中掉帧
            beyondViewportPageCount = 1,
            modifier = Modifier.fillMaxSize()
        ) { page ->
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.TopStart
            ) {
                when (page) {
                    0 -> CompanionStatusTab(
                        uiState = statusUiState,
                        clockFlow = clockFlow,
                        onRefresh = onRefreshStatus
                    )
                    1 -> CompanionScheduleTab(uiState = statusUiState)
                    2 -> CompanionModelTab(
                        availableModels = availableModels,
                        selectedModel = selectedModel,
                        isLoading = modelLoading,
                        error = modelError,
                        onModelSelected = onModelSelected,
                        thinkingEnabled = thinkingEnabled,
                        onThinkingChange = onThinkingChange
                    )
                    3 -> CompanionPersonaTab(
                        uiState = personaUiState,
                        viewingFilename = viewingFilename,
                        onSwitchPersona = onSwitchPersona,
                        onSelectVoice = onSelectVoice,
                        onResetVoice = onResetVoice
                    )
                    4 -> CompanionMemoryTab(
                        companionName = companionName,
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
                        onLoadMoreMemory = onLoadMoreMemory,
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
 * Tab 栏：纯文字 + 选中项底部 2dp 内阴影线。
 *
 * `pagerState.currentPage` 只在**这一层**读取：它会在滑动经过页面中点时变一次，
 * 如果在上面的 [CompanionScreen] 里读，整屏（页头 + Pager + 五个页面）都会跟着重组，
 * 长列表页（模型选择、记忆树）会因此明显掉帧。
 */
@Composable
private fun CompanionTabRow(
    tabs: List<String>,
    pagerState: PagerState,
    scope: CoroutineScope
) {
    val selectedIndex = pagerState.currentPage
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = CompanionGutter),
            horizontalArrangement = Arrangement.spacedBy(TabGap)
        ) {
            tabs.forEachIndexed { index, title ->
                val selected = selectedIndex == index
                Box(
                    modifier = Modifier
                        .height(40.dp)
                        .drawBehind {
                            if (selected) {
                                val stroke = 2.dp.toPx()
                                drawLine(
                                    color = TextPrimary,
                                    start = Offset(0f, size.height - stroke / 2f),
                                    end = Offset(size.width, size.height - stroke / 2f),
                                    strokeWidth = stroke
                                )
                            }
                        }
                        .clickable(
                            interactionSource = remember { MutableInteractionSource() },
                            indication = null
                        ) {
                            scope.launch { pagerState.animateScrollToPage(index) }
                        },
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = title,
                        style = MaterialTheme.typography.labelLarge,
                        color = if (selected) TextPrimary else TextTertiary,
                        fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                        maxLines = 1,
                        softWrap = false
                    )
                }
            }
        }
        HorizontalDivider(color = Line, thickness = 1.dp)
    }
}
