package com.aveline.ai.mobile.presentation.companion

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.Memory
import com.aveline.ai.mobile.domain.models.MemorySortOrder
import com.aveline.ai.mobile.presentation.companion.memory.ConversationTreeToolbar
import com.aveline.ai.mobile.presentation.companion.memory.EmptyConversationTreeState
import com.aveline.ai.mobile.presentation.companion.memory.EmptyMemoryState
import com.aveline.ai.mobile.presentation.companion.memory.MemoryDetailDialog
import com.aveline.ai.mobile.presentation.companion.memory.MemoryFilterBar
import com.aveline.ai.mobile.presentation.companion.memory.MemoryGraphSection
import com.aveline.ai.mobile.presentation.companion.memory.MemoryOverviewCard
import com.aveline.ai.mobile.presentation.companion.memory.MemoryTimeBucket
import com.aveline.ai.mobile.presentation.companion.memory.MemoryTreeToolbar
import com.aveline.ai.mobile.presentation.companion.memory.MemoryViewMode
import com.aveline.ai.mobile.presentation.companion.memory.MemoryViewModeSwitcher
import com.aveline.ai.mobile.presentation.companion.memory.buildConversationTreeRows
import com.aveline.ai.mobile.presentation.companion.memory.buildMemoryTree
import com.aveline.ai.mobile.presentation.companion.memory.conversationBranchParentIds
import com.aveline.ai.mobile.presentation.companion.memory.conversationTreeItems
import com.aveline.ai.mobile.presentation.companion.memory.hasVisibleContent
import com.aveline.ai.mobile.presentation.companion.memory.mergeConversationMessages
import com.aveline.ai.mobile.presentation.companion.memory.memoryTreeItems
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.memory.MemoryGraphUiState
import com.aveline.ai.mobile.presentation.memory.MemoryUiState
import com.aveline.ai.mobile.presentation.theme.Primary

/**
 * Companion 记忆 Tab。
 *
 * 顶部是两种视图的切换按钮，点一下原地切换：
 * - 聊天树：本地消息库的完整对话树，重新生成 / 编辑产生的平行分支各成一条世界线；
 * - 加权记忆：后端加权记忆，按「时间桶 → 话题 → 条目」三层展示。
 *
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
 * @param onMemoryClick 点击记忆卡片(查看详情)回调
 * @param onCloseDetail 关闭记忆详情弹窗回调
 * @param graphUiState 记忆网络（地标 / 邻域 / 关联）状态
 * @param onGraphEnter 进入记忆网络时加载地标
 * @param onGraphAnchorClick 展开某个地标
 * @param onGraphBack 退回地标层
 * @param onGraphRetry 记忆网络加载失败重试
 */
@Composable
fun CompanionMemoryTab(
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
    onMemoryClick: (Memory) -> Unit,
    onCloseDetail: () -> Unit,
    graphUiState: MemoryGraphUiState,
    onGraphEnter: () -> Unit,
    onGraphAnchorClick: (String) -> Unit,
    onGraphBack: () -> Unit,
    onGraphRetry: () -> Unit
) {
    // 用 name 保存，避免依赖 Bundle 对 enum 的序列化行为
    var viewModeName by rememberSaveable { mutableStateOf(MemoryViewMode.CONVERSATION.name) }
    val viewMode = MemoryViewMode.valueOf(viewModeName)
    var conversationActiveOnly by rememberSaveable { mutableStateOf(false) }
    var expandedConversationBranches by remember { mutableStateOf<Set<String>>(emptySet()) }

    // 本地消息树（含分支）+ 服务端历史（Windows / 其他平台）
    val conversationMessages = remember(
        uiState.conversationMessages,
        uiState.remoteConversationMessages
    ) {
        mergeConversationMessages(
            local = uiState.conversationMessages,
            remote = uiState.remoteConversationMessages
        )
    }

    val conversationRows = remember(
        conversationMessages,
        expandedConversationBranches,
        conversationActiveOnly
    ) {
        buildConversationTreeRows(
            messages = conversationMessages,
            expandedBranches = expandedConversationBranches,
            activeOnly = conversationActiveOnly
        )
    }
    val conversationBranchParents = remember(conversationMessages) {
        conversationBranchParentIds(conversationMessages)
    }

    // filteredMemories 是 computed property，直接读会每次重组都重新过滤 + 排序；
    // 这里只在筛选条件或源数据变化时重算，树构建也复用同一份结果。
    val filteredMemories = remember(
        uiState.memories,
        uiState.selectedTopic,
        uiState.showImportantOnly,
        uiState.searchQuery,
        uiState.sortOrder
    ) { uiState.filteredMemories }

    val groups = remember(filteredMemories, uiState.sortOrder) {
        buildMemoryTree(filteredMemories, uiState.sortOrder)
    }
    val visibleCount = remember(filteredMemories) {
        filteredMemories.count { it.hasVisibleContent() }
    }

    // 搜索 / 话题 / 重要筛选生效时强制展开，避免结果被折叠节点藏起来。
    val forceExpand = uiState.searchQuery.isNotBlank() ||
        uiState.selectedTopic != null ||
        uiState.showImportantOnly

    val firstBucket = groups.firstOrNull()
    val defaultTopicKeys = remember(firstBucket?.bucket?.name) {
        val bucket = firstBucket
        if (bucket == null) {
            emptySet<String>()
        } else {
            bucket.topics.take(3).mapTo(HashSet()) { "${bucket.bucket.name}/${it.key}" }
        }
    }

    var bucketOverrides by remember { mutableStateOf<Map<String, Boolean>>(emptyMap()) }
    var topicOverrides by remember { mutableStateOf<Map<String, Boolean>>(emptyMap()) }

    val isBucketExpanded: (MemoryTimeBucket) -> Boolean = { bucket ->
        forceExpand || (bucketOverrides[bucket.name] ?: (bucket.name == firstBucket?.bucket?.name))
    }
    val isTopicExpanded: (String, String) -> Boolean = { bucketName, topicKey ->
        val composite = "$bucketName/$topicKey"
        forceExpand || (topicOverrides[composite] ?: (composite in defaultTopicKeys))
    }

    val allExpanded = groups.isNotEmpty() && groups.all { bucket ->
        isBucketExpanded(bucket.bucket) &&
            bucket.topics.all { isTopicExpanded(bucket.bucket.name, it.key) }
    }

    val weightedActionLabel = when {
        forceExpand -> "重置筛选"
        allExpanded -> "全部收起"
        else -> "全部展开"
    }
    val onWeightedAction: () -> Unit = {
        if (forceExpand) {
            onClearFilters()
        } else {
            val target = !allExpanded
            bucketOverrides = groups.associate { it.bucket.name to target }
            topicOverrides = groups
                .flatMap { bucket -> bucket.topics.map { "${bucket.bucket.name}/${it.key}" } }
                .associateWith { target }
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 16.dp),
            contentPadding = PaddingValues(top = 8.dp, bottom = 28.dp)
        ) {
            item(key = "memory-view-mode") {
                MemoryViewModeSwitcher(
                    mode = viewMode,
                    onModeChange = { viewModeName = it.name },
                    modifier = Modifier.padding(bottom = 8.dp)
                )
            }

            if (viewMode == MemoryViewMode.CONVERSATION) {
                if (conversationMessages.isEmpty()) {
                    item(key = "conversation-empty") {
                        SectionCard(title = "聊天记录树") {
                            EmptyConversationTreeState()
                        }
                    }
                } else {
                    item(key = "conversation-toolbar") {
                        ConversationTreeToolbar(
                            messageCount = conversationMessages.size,
                            branchCount = conversationBranchParents.size,
                            activeOnly = conversationActiveOnly,
                            actionLabel = if (expandedConversationBranches.isEmpty()) "展开全部分支" else "收起全部分支",
                            onToggleActiveOnly = {
                                conversationActiveOnly = !conversationActiveOnly
                            },
                            onAction = {
                                expandedConversationBranches =
                                    if (expandedConversationBranches.isEmpty()) {
                                        conversationBranchParents
                                    } else {
                                        emptySet()
                                    }
                            }
                        )
                    }
                    conversationTreeItems(
                        rows = conversationRows,
                        onExpandBranch = { parentId ->
                            expandedConversationBranches = expandedConversationBranches + parentId
                        }
                    )
                }
            } else if (viewMode == MemoryViewMode.WEIGHTED) {
                item(key = "memory-overview") {
                    MemoryOverviewCard(
                        memories = uiState.memories,
                        selectedTopic = uiState.selectedTopic,
                        onTopicSelect = onTopicFilterChange
                    )
                }

                item(key = "memory-filter") {
                    SectionCard(
                        title = "搜索与筛选",
                        modifier = Modifier.padding(top = 12.dp)
                    ) {
                        MemoryFilterBar(
                            searchQuery = uiState.searchQuery,
                            showImportantOnly = uiState.showImportantOnly,
                            sortOrder = uiState.sortOrder,
                            hasFilters = uiState.hasFilters,
                            resultCount = visibleCount,
                            onSearch = onSearch,
                            onToggleImportantOnly = onToggleImportantOnly,
                            onSortOrderChange = onSortOrderChange,
                            onClearFilters = onClearFilters
                        )
                    }
                }

                when {
                    uiState.isLoading -> {
                        item(key = "memory-loading") {
                            SectionCard(
                                title = "记忆树",
                                modifier = Modifier.padding(top = 12.dp)
                            ) {
                                Box(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(vertical = 32.dp),
                                    contentAlignment = Alignment.Center
                                ) {
                                    CircularProgressIndicator(color = Primary)
                                }
                            }
                        }
                    }

                    groups.isEmpty() -> {
                        item(key = "memory-empty") {
                            SectionCard(
                                title = "记忆树",
                                modifier = Modifier.padding(top = 12.dp)
                            ) {
                                EmptyMemoryState(
                                    hasFilters = uiState.hasFilters,
                                    onClearFilters = onClearFilters
                                )
                            }
                        }
                    }

                    else -> {
                        item(key = "memory-tree-toolbar") {
                            MemoryTreeToolbar(
                                total = visibleCount,
                                actionLabel = weightedActionLabel,
                                onAction = onWeightedAction,
                                modifier = Modifier.padding(top = 8.dp)
                            )
                        }
                        memoryTreeItems(
                            groups = groups,
                            isBucketExpanded = isBucketExpanded,
                            isTopicExpanded = isTopicExpanded,
                            onToggleBucket = { bucket ->
                                bucketOverrides = bucketOverrides +
                                    (bucket.name to !isBucketExpanded(bucket))
                            },
                            onToggleTopic = { bucketName, topicKey ->
                                val composite = "$bucketName/$topicKey"
                                topicOverrides = topicOverrides +
                                    (composite to !isTopicExpanded(bucketName, topicKey))
                            },
                            onMemoryClick = onMemoryClick,
                            onToggleImportant = onToggleImportant,
                            onDelete = onDeleteMemory
                        )
                    }
                }
            } else {
                item(key = "memory-graph") {
                    MemoryGraphSection(
                        state = graphUiState,
                        onEnter = onGraphEnter,
                        onAnchorClick = onGraphAnchorClick,
                        onNodeClick = onMemoryClick,
                        onBack = onGraphBack,
                        onRetry = onGraphRetry,
                        modifier = Modifier.padding(top = 8.dp)
                    )
                }
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
                        onClick = onConfirmDelete,
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
            MemoryDetailDialog(
                memory = selectedMemory,
                relations = graphUiState.relations,
                relationsLoading = graphUiState.isLoadingRelations,
                onClose = onCloseDetail,
                onToggleImportant = { onToggleImportant(selectedMemory) },
                onDelete = { onDeleteMemory(selectedMemory) },
                onRelationClick = onMemoryClick
            )
        }
    }
}
