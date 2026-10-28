package com.aveline.ai.mobile.presentation.memory

import com.aveline.ai.mobile.domain.models.Memory
import com.aveline.ai.mobile.domain.models.MemorySortOrder
import com.aveline.ai.mobile.domain.models.MemoryStats
import com.aveline.ai.mobile.domain.models.Message

/**
 * 记忆管理 UI 状态
 *
 * @property memories 记忆列表
 * @property searchQuery 搜索关键词
 * @property selectedTopic 选中的话题过滤（后端 category 大量为 uncategorized，改用 topics 归组）
 * @property sortOrder 排序方式
 * @property stats 记忆统计
 * @property isLoading 首屏是否加载中
 * @property isLoadingMore 是否正在加载下一页
 * @property hasMore 是否还有下一页
 * @property error 错误信息
 * @property showDeleteConfirm 是否显示删除确认
 * @property memoryToDelete 待删除的记忆
 * @property showMemoryDetail 是否显示记忆详情弹窗
 * @property selectedMemory 当前正在查看详情的记忆
 * @property conversationMessages 当前会话的全量消息树（含重新生成 / 编辑产生的平行分支）
 * @property remoteConversationMessages 服务端聊天历史（Windows / 其他平台，只读展示）
 */
data class MemoryUiState(
    val memories: List<Memory> = emptyList(),
    val conversationMessages: List<Message> = emptyList(),
    val remoteConversationMessages: List<Message> = emptyList(),
    val searchQuery: String = "",
    val selectedTopic: String? = null,
    val sortOrder: MemorySortOrder = MemorySortOrder.NEWEST_FIRST,
    val stats: MemoryStats? = null,
    val isLoading: Boolean = false,
    val isLoadingMore: Boolean = false,
    val hasMore: Boolean = false,
    val error: String? = null,
    val showDeleteConfirm: Boolean = false,
    val memoryToDelete: Memory? = null,
    val showImportantOnly: Boolean = false,
    val availableTags: List<String> = emptyList(),
    val showMemoryDetail: Boolean = false,
    val selectedMemory: Memory? = null
) {
    val filteredMemories: List<Memory>
        get() {
            var result = memories

            if (selectedTopic != null) {
                result = result.filter { it.topicKey == selectedTopic }
            }

            if (showImportantOnly) {
                result = result.filter { it.isImportant }
            }

            if (searchQuery.isNotBlank()) {
                result = result.filter {
                    it.displayContent.contains(searchQuery, ignoreCase = true) ||
                    it.tags.any { tag -> tag.contains(searchQuery, ignoreCase = true) }
                }
            }

            return when (sortOrder) {
                MemorySortOrder.NEWEST_FIRST -> result.sortedByDescending { it.createdAt }
                MemorySortOrder.OLDEST_FIRST -> result.sortedBy { it.createdAt }
                MemorySortOrder.MOST_ACCESSED -> result.sortedByDescending { it.accessCount }
                MemorySortOrder.MOST_IMPORTANT -> result.sortedByDescending { it.importance }
            }
        }

    val hasMemories: Boolean
        get() = memories.isNotEmpty()

    val hasFilters: Boolean
        get() = selectedTopic != null || showImportantOnly || searchQuery.isNotBlank()
}
