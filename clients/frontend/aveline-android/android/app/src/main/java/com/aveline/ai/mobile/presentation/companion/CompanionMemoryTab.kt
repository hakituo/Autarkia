package com.aveline.ai.mobile.presentation.companion

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.Memory
import com.aveline.ai.mobile.domain.models.MemorySortOrder
import com.aveline.ai.mobile.presentation.companion.memory.MemoryConversationPane
import com.aveline.ai.mobile.presentation.companion.memory.MemoryDetailSheet
import com.aveline.ai.mobile.presentation.companion.memory.MemoryGraphSection
import com.aveline.ai.mobile.presentation.companion.memory.MemoryViewMode
import com.aveline.ai.mobile.presentation.companion.memory.MemoryViewModeSwitcher
import com.aveline.ai.mobile.presentation.companion.memory.MemoryWeightedPane
import com.aveline.ai.mobile.presentation.memory.MemoryGraphUiState
import com.aveline.ai.mobile.presentation.memory.MemoryUiState

/**
 * Companion 记忆 Tab。
 *
 * 顶部三个分段切三种看法，切换原地完成，不跳页：
 * - 聊天树：本地消息库的完整对话树，重新生成 / 编辑产生的平行分支各成一条世界线；
 * - 加权记忆：后端加权记忆，按「时间桶 → 话题 → 条目」三层展示；
 * - 记忆网络：按关系扩散的地标 / 邻域图。
 *
 * 三个视图都用同一套左右留白，`SectionCard` 和它的副标题一概不用——
 * 「记忆档案」「搜索与筛选」「记忆树」这些卡片标题只是把开发结构翻译了一遍。
 *
 * @param companionName AI 发言时的署名
 * @param uiState 记忆页 UI 状态
 * @param onSearch 搜索回调
 * @param onTopicFilterChange 话题筛选回调
 * @param onToggleImportantOnly 切换只看重要回调
 * @param onSortOrderChange 排序回调
 * @param onDeleteMemory 删除记忆回调
 * @param onToggleImportant 切换重要标记回调
 * @param onConfirmDelete 确认删除回调
 * @param onCancelDelete 取消删除回调
 * @param onClearFilters 清除过滤回调
 * @param onLoadMoreMemory 滚动到底部加载下一页回调
 * @param onMemoryClick 点击记忆卡片(查看详情)回调
 * @param onCloseDetail 关闭记忆详情面板回调
 * @param graphUiState 记忆网络（地标 / 邻域 / 关联）状态
 * @param onGraphEnter 进入记忆网络时加载地标
 * @param onGraphAnchorClick 展开某个地标 / 以某条记忆为中心
 * @param onGraphBack 退回地标层
 * @param onGraphRetry 记忆网络加载失败重试
 */
@Composable
fun CompanionMemoryTab(
    companionName: String,
    uiState: MemoryUiState,
    onSearch: (String) -> Unit,
    onTopicFilterChange: (String?) -> Unit,
    onToggleImportantOnly: () -> Unit,
    onSortOrderChange: (MemorySortOrder) -> Unit,
    onDeleteMemory: (Memory) -> Unit,
    onToggleImportant: (Memory) -> Unit,
    onConfirmDelete: () -> Unit,
    onCancelDelete: () -> Unit,
    onClearFilters: () -> Unit,
    onLoadMoreMemory: () -> Unit,
    onMemoryClick: (Memory) -> Unit,
    onCloseDetail: () -> Unit,
    graphUiState: MemoryGraphUiState,
    onGraphEnter: () -> Unit,
    onGraphAnchorClick: (String) -> Unit,
    onGraphBack: () -> Unit,
    onGraphRetry: () -> Unit
) {
    // 用 name 保存，避免依赖 Bundle 对 enum 的序列化行为
    var viewModeName by rememberSaveable { mutableStateOf(MemoryViewMode.WEIGHTED.name) }
    val viewMode = MemoryViewMode.valueOf(viewModeName)

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = CompanionGutter)
    ) {
        MemoryViewModeSwitcher(
            mode = viewMode,
            onModeChange = { viewModeName = it.name },
            modifier = Modifier.padding(top = 12.dp, bottom = 2.dp)
        )

        when (viewMode) {
            MemoryViewMode.CONVERSATION -> MemoryConversationPane(
                localMessages = uiState.conversationMessages,
                remoteMessages = uiState.remoteConversationMessages,
                companionName = companionName
            )

            MemoryViewMode.WEIGHTED -> MemoryWeightedPane(
                uiState = uiState,
                onSearch = onSearch,
                onTopicFilterChange = onTopicFilterChange,
                onToggleImportantOnly = onToggleImportantOnly,
                onSortOrderChange = onSortOrderChange,
                onClearFilters = onClearFilters,
                onMemoryClick = onMemoryClick,
                onDeleteMemory = onDeleteMemory,
                onLoadMore = onLoadMoreMemory
            )

            MemoryViewMode.GRAPH -> MemoryGraphSection(
                state = graphUiState,
                onEnter = onGraphEnter,
                onAnchorClick = onGraphAnchorClick,
                onNodeClick = onMemoryClick,
                onRecenter = onGraphAnchorClick,
                onBack = onGraphBack,
                onRetry = onGraphRetry,
                modifier = Modifier.padding(top = 4.dp)
            )
        }
    }

    val memoryToDelete = uiState.memoryToDelete
    if (uiState.showDeleteConfirm && memoryToDelete != null) {
        AlertDialog(
            onDismissRequest = onCancelDelete,
            title = { Text("删除记忆") },
            text = {
                Text("确定要删除这条记忆吗？\n\n“${memoryToDelete.displayContent.take(80)}…”")
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        // 删除成功后详情面板不该继续展示一条已经不存在的记忆
                        onConfirmDelete()
                        onCloseDetail()
                    },
                    colors = ButtonDefaults.textButtonColors(
                        contentColor = MaterialTheme.colorScheme.error
                    )
                ) {
                    Text("删除")
                }
            },
            dismissButton = {
                TextButton(onClick = onCancelDelete) {
                    Text("取消")
                }
            }
        )
    }

    val selectedMemory = uiState.selectedMemory
    if (uiState.showMemoryDetail && selectedMemory != null) {
        MemoryDetailSheet(
            memory = selectedMemory,
            relations = graphUiState.relations,
            relationsLoading = graphUiState.isLoadingRelations,
            onClose = onCloseDetail,
            onToggleImportant = { onToggleImportant(selectedMemory) },
            onDelete = {
                // 先收起面板再弹确认框：底部面板和对话框叠在一起时，
                // 确认按钮会被面板挡住，用户会以为点了没反应。
                onCloseDetail()
                onDeleteMemory(selectedMemory)
            },
            onRelationClick = onMemoryClick
        )
    }
}
