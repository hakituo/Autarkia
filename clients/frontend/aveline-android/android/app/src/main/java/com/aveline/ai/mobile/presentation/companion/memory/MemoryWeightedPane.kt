package com.aveline.ai.mobile.presentation.companion.memory

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.Memory
import com.aveline.ai.mobile.domain.models.MemorySortOrder
import com.aveline.ai.mobile.presentation.memory.MemoryUiState
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filter

/**
 * 加权记忆视图。
 *
 * 结构是「搜索栏 → 排序文字 Tab → 计数一行 → 时间桶 → 话题 → 条目」。
 * 时间桶只做小标题，话题是一行可展开的条目，展开后的记忆挂在左侧一条细线下——
 * 原来三层各套一张卡片、各配一个数量徽章，同一条信息被强调了三次。
 */
@Composable
internal fun MemoryWeightedPane(
    uiState: MemoryUiState,
    onSearch: (String) -> Unit,
    onTopicFilterChange: (String?) -> Unit,
    onToggleImportantOnly: () -> Unit,
    onSortOrderChange: (MemorySortOrder) -> Unit,
    onClearFilters: () -> Unit,
    onMemoryClick: (Memory) -> Unit,
    onDeleteMemory: (Memory) -> Unit,
    onLoadMore: () -> Unit,
    modifier: Modifier = Modifier
) {
    var filtersExpanded by rememberSaveable { mutableStateOf(false) }
    val listState = rememberLazyListState()

    // 滚到接近底部才请求下一页；用户还没滑动过时不自动加载，
    // 避免树默认折叠、列表不足一屏时把整库一口气拉完。
    LaunchedEffect(
        listState,
        uiState.hasMore,
        uiState.isLoadingMore,
        uiState.memories.size
    ) {
        if (!uiState.hasMore || uiState.isLoadingMore) return@LaunchedEffect
        snapshotFlow {
            val layoutInfo = listState.layoutInfo
            val lastVisible = layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: -1
            val reachedBottom = layoutInfo.totalItemsCount > 0 &&
                lastVisible >= layoutInfo.totalItemsCount - 3
            val userScrolled = listState.firstVisibleItemIndex > 0 ||
                listState.firstVisibleItemScrollOffset > 0
            reachedBottom && userScrolled
        }
            .distinctUntilChanged()
            .filter { it }
            .collect { onLoadMore() }
    }

    val visibleMemories = remember(uiState.memories) {
        uiState.memories.filter { it.hasVisibleContent() }
    }
    val topics = remember(visibleMemories) { topicCounts(visibleMemories) }
    val importantCount = remember(visibleMemories) { visibleMemories.count { it.isImportant } }

    // filteredMemories 是 computed property，直接读会每次重组都重新过滤 + 排序；
    // 这里只在筛选条件或源数据变化时重算，树构建也复用同一份结果。
    val filtered = remember(
        uiState.memories,
        uiState.selectedTopic,
        uiState.showImportantOnly,
        uiState.searchQuery,
        uiState.sortOrder
    ) { uiState.filteredMemories }
    val groups = remember(filtered, uiState.sortOrder) {
        buildMemoryTree(filtered, uiState.sortOrder)
    }
    val visibleCount = remember(filtered) { filtered.count { it.hasVisibleContent() } }

    // 搜索 / 话题 / 重要筛选生效时强制展开，避免结果被折叠节点藏起来。
    val forceExpand = uiState.searchQuery.isNotBlank() ||
        uiState.selectedTopic != null ||
        uiState.showImportantOnly

    val firstBucket = groups.firstOrNull()
    // 只展开第一个时间桶的前三个话题：默认全展开等于一屏几十条，用户找不到入口
    val defaultTopicKeys: Set<String> = if (firstBucket == null) {
        emptySet()
    } else {
        firstBucket.topics.take(3).mapTo(HashSet()) { "${firstBucket.bucket.name}/${it.key}" }
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
    val actionLabel = when {
        forceExpand -> "重置筛选"
        allExpanded -> "全部收起"
        else -> "全部展开"
    }
    val onAction: () -> Unit = {
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

    LazyColumn(
        state = listState,
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(bottom = 24.dp)
    ) {
        item(key = "memory-search") {
            MemorySearchRow(
                query = uiState.searchQuery,
                hasFilters = uiState.hasFilters,
                expanded = filtersExpanded,
                onQueryChange = onSearch,
                onToggleFilters = { filtersExpanded = !filtersExpanded },
                modifier = Modifier.padding(top = 12.dp)
            )
        }

        if (filtersExpanded) {
            item(key = "memory-filters") {
                MemoryFilterPanel(
                    topics = topics,
                    totalCount = visibleMemories.size,
                    selectedTopic = uiState.selectedTopic,
                    showImportantOnly = uiState.showImportantOnly,
                    hasFilters = uiState.hasFilters,
                    onTopicSelect = onTopicFilterChange,
                    onToggleImportantOnly = onToggleImportantOnly,
                    onClearFilters = onClearFilters,
                    modifier = Modifier.padding(top = 10.dp)
                )
            }
        }

        item(key = "memory-sort") {
            MemorySortTabs(
                sortOrder = uiState.sortOrder,
                onSortOrderChange = onSortOrderChange,
                modifier = Modifier.padding(top = 10.dp)
            )
        }

        item(key = "memory-summary") {
            MemorySummaryRow(
                summary = "$visibleCount 条 · $importantCount 条重要 · ${topics.size} 个话题",
                actionLabel = actionLabel,
                onAction = onAction,
                modifier = Modifier.padding(top = 2.dp, bottom = 2.dp)
            )
        }

        when {
            uiState.isLoading && groups.isEmpty() -> item(key = "memory-loading") {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 40.dp),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator(color = Accent)
                }
            }

            groups.isEmpty() -> item(key = "memory-empty") {
                EmptyMemoryState(
                    hasFilters = uiState.hasFilters,
                    onClearFilters = onClearFilters
                )
            }

            else -> memoryTreeItems(
                groups = groups,
                isBucketExpanded = isBucketExpanded,
                isTopicExpanded = isTopicExpanded,
                onToggleBucket = { bucket ->
                    bucketOverrides = bucketOverrides + (bucket.name to !isBucketExpanded(bucket))
                },
                onToggleTopic = { bucketName, topicKey ->
                    val composite = "$bucketName/$topicKey"
                    topicOverrides = topicOverrides +
                        (composite to !isTopicExpanded(bucketName, topicKey))
                },
                onMemoryClick = onMemoryClick,
                onDelete = onDeleteMemory
            )
        }

        when {
            uiState.isLoadingMore -> item(key = "memory-load-more") {
                MemoryLoadMoreRow(isLoading = true, onClick = onLoadMore)
            }

            uiState.hasMore -> item(key = "memory-load-more") {
                MemoryLoadMoreRow(isLoading = false, onClick = onLoadMore)
            }
        }
    }
}

/** 列表底部的加载态；列表不足一屏时用户也可以点它继续拉下一页。 */
@Composable
private fun MemoryLoadMoreRow(
    isLoading: Boolean,
    onClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(enabled = !isLoading, onClick = onClick)
            .padding(vertical = 18.dp),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically
    ) {
        if (isLoading) {
            CircularProgressIndicator(
                modifier = Modifier.size(16.dp),
                strokeWidth = 2.dp,
                color = Accent
            )
            Spacer(modifier = Modifier.width(8.dp))
        }
        Text(
            text = if (isLoading) "正在加载…" else "继续下滑加载更多",
            style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp),
            color = TextSecondary
        )
    }
}
