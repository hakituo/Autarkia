package com.aveline.ai.mobile.presentation.memory

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.domain.models.*
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.domain.repository.MemoryRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

/** 记忆管理 ViewModel：列表分页、搜索过滤、删除/标重要，以及聊天记录与记忆网络的转发。 */
@HiltViewModel
class MemoryViewModel @Inject constructor(
    private val memoryRepository: MemoryRepository,
    private val chatRepository: ChatRepository
) : ViewModel() {

    private companion object {
        const val TAG = "MemoryViewModel"
    }

    private val _uiState = MutableStateFlow(MemoryUiState())
    val uiState: StateFlow<MemoryUiState> = _uiState.asStateFlow()

    /** 记忆网络（地标 / 邻域 / 「想起…」）的加载器：列表管理不掺和图的事 */
    private val graphCoordinator = MemoryGraphCoordinator(memoryRepository, viewModelScope)
    val graphState: StateFlow<MemoryGraphUiState> = graphCoordinator.state

    private var searchJob: Job? = null
    private val searchDebounceMs = 300L

    private var loadJob: Job? = null
    private var loadMoreJob: Job? = null

    /** 下一页的 offset；以服务端实际返回条数累加，避免客户端过滤后错位 */
    private var nextOffset = 0

    /** 列表代次：切角色 / 排序 / 搜索时递增，丢弃迟到的旧分页结果 */
    private var pageGeneration = 0

    /** 当前正在查看的 persona 文件名（来自聊天会话/伴侣面板选择，纯只读）；为 null 表示用后端默认 */
    @Volatile
    private var currentProfileFilename: String? = null

    /** 「聊天记录」视图的数据源：本地树 + 服务端历史 */
    private val conversationCoordinator = MemoryConversationCoordinator(chatRepository, viewModelScope)

    /** 首轮记忆列表 / 统计 / 标签是否已经拉过（避免按 null persona 白拉一轮）。 */
    private var initialLoadStarted = false

    /**
     * 首轮加载（幂等），由先确定上下文的调用方触发：聊天页进页走 [setViewingPersona]，
     * 深链只给 role 时由详情面板调 [ensureLoaded] 兜底。
     */
    private fun loadAllForCurrentContext() {
        initialLoadStarted = true
        viewModelScope.launch(Dispatchers.IO) {
            loadMemories()
            loadStats()
            loadTags()
        }
    }

    /** 兜底首轮加载：已经拉过就什么都不做。 */
    fun ensureLoaded() {
        if (initialLoadStarted) return
        loadAllForCurrentContext()
    }

    /**
     * 设置“正在查看的角色”对应的 persona 文件名（纯只读查询，不切对话人设）。
     * 由 ChatScreen 在聊天进入 / 面板内选版本时调用。
     */
    fun setViewingPersona(filename: String) {
        if (filename.isBlank() || filename == currentProfileFilename) return
        currentProfileFilename = filename
        Log.d(TAG, "查看角色 persona 文件名: $filename")
        // 地标与关系都是按角色算的，换角色必须作废旧结果
        graphCoordinator.reset()
        loadAllForCurrentContext()
    }

    /**
     * 设置「正在查看的聊天会话」，用于展示完整聊天记录树（含所有平行分支）。
     * 与 setViewingPersona 一样是只读注入：只切数据源，不切换聊天会话本身。
     */
    fun setViewingSession(sessionId: String?) {
        conversationCoordinator.setSession(
            sessionId = sessionId,
            onLocalMessages = { messages ->
                _uiState.update { it.copy(conversationMessages = messages) }
            },
            onRemoteMessages = { messages ->
                _uiState.update { it.copy(remoteConversationMessages = messages) }
            }
        )
    }

    /**
     * 加载首屏记忆列表（offset 归零）
     */
    fun loadMemories() {
        val generation = ++pageGeneration
        loadJob?.cancel()
        loadMoreJob?.cancel()
        loadMoreJob = null
        loadJob = viewModelScope.launch {
            _uiState.update {
                it.copy(isLoading = true, isLoadingMore = false, error = null)
            }

            // 类型 / 话题 / 重要筛选全部在客户端完成：后端只支持 category 过滤，
            // 而历史记忆的 category 基本是 uncategorized，按类型请求会直接把列表筛空。
            val page = memoryRepository.getMemories(
                MemoryFilter(),
                _uiState.value.sortOrder,
                persona = currentProfileFilename,
                offset = 0,
                limit = MEMORY_PAGE_SIZE
            )
            if (generation != pageGeneration) return@launch
            nextOffset = page.memories.size

            _uiState.update {
                it.copy(
                    memories = page.memories,
                    isLoading = false,
                    hasMore = page.hasMore
                )
            }
        }
    }

    /**
     * 滚动到底部时加载下一页，追加到已有列表。
     */
    fun loadMoreMemories() {
        val state = _uiState.value
        if (state.isLoading || state.isLoadingMore || !state.hasMore) return

        val offset = nextOffset
        val generation = pageGeneration
        loadMoreJob = viewModelScope.launch {
            _uiState.update { it.copy(isLoadingMore = true) }

            val page = memoryRepository.getMemories(
                MemoryFilter(),
                _uiState.value.sortOrder,
                persona = currentProfileFilename,
                offset = offset,
                limit = MEMORY_PAGE_SIZE
            )
            if (generation != pageGeneration) return@launch
            nextOffset = offset + page.memories.size

            _uiState.update { current ->
                val existingIds = current.memories.mapTo(HashSet()) { it.id }
                val appended = page.memories.filterNot { it.id in existingIds }
                current.copy(
                    memories = current.memories + appended,
                    isLoadingMore = false,
                    // 整页都是重复说明服务端没有按 offset 前进，停下比空转更安全
                    hasMore = page.hasMore && appended.isNotEmpty()
                )
            }
        }
    }

    private fun loadStats() {
        viewModelScope.launch {
            val stats = memoryRepository.getMemoryStats(persona = currentProfileFilename)
            _uiState.update { it.copy(stats = stats) }
        }
    }

    private fun loadTags() {
        viewModelScope.launch {
            val tags = memoryRepository.getTags(persona = currentProfileFilename)
            _uiState.update { it.copy(availableTags = tags) }
        }
    }
    
    /**
     * 搜索记忆（带防抖）
     */
    fun search(query: String) {
        _uiState.update { it.copy(searchQuery = query) }
        
        searchJob?.cancel()
        loadMoreJob?.cancel()
        
        if (query.isBlank()) {
            loadMemories()
            return
        }

        val generation = ++pageGeneration
        searchJob = viewModelScope.launch {
            delay(searchDebounceMs)

            _uiState.update { it.copy(isLoading = true, isLoadingMore = false) }

            val results = memoryRepository.searchMemories(query, persona = currentProfileFilename)
            if (generation != pageGeneration) return@launch
            nextOffset = results.size
            
            _uiState.update { 
                it.copy(
                    memories = results,
                    isLoading = false,
                    hasMore = false
                )
            }
        }
    }
    
    /**
     * 设置话题过滤（本地筛选，不需要重新请求后端）
     */
    fun setTopicFilter(topic: String?) {
        _uiState.update { it.copy(selectedTopic = topic) }
    }
    
    /**
     * 切换只显示重要（本地过滤）
     */
    fun toggleImportantOnly() {
        _uiState.update { it.copy(showImportantOnly = !it.showImportantOnly) }
    }
    
    /**
     * 设置排序方式。
     *
     * 分页后不能再只重排已加载的部分，否则跨页顺序会错；排序切换时从 offset=0 重拉。
     * 搜索结果是一次性取回的完整集合，仍然本地排序即可。
     */
    fun setSortOrder(order: MemorySortOrder) {
        if (_uiState.value.sortOrder == order) return
        _uiState.update { it.copy(sortOrder = order) }
        if (_uiState.value.searchQuery.isBlank()) {
            loadMemories()
        }
    }
    
    /**
     * 删除记忆
     */
    fun deleteMemory(memory: Memory) {
        _uiState.update { 
            it.copy(
                showDeleteConfirm = true,
                memoryToDelete = memory
            )
        }
    }
    
    /**
     * 确认删除
     */
    fun confirmDelete() {
        val memory = _uiState.value.memoryToDelete ?: return
        
        viewModelScope.launch {
            val result = memoryRepository.deleteMemory(memory.id)
            
            result.fold(
                onSuccess = {
                    // 服务端删掉一条后，后面的条目整体前移，下一页 offset 要跟着减一
                    nextOffset = (nextOffset - 1).coerceAtLeast(0)
                    _uiState.update { 
                        it.copy(
                            memories = it.memories.filter { m -> m.id != memory.id },
                            showDeleteConfirm = false,
                            memoryToDelete = null
                        )
                    }
                    loadStats()
                },
                onFailure = { e ->
                    _uiState.update { 
                        it.copy(
                            error = "删除失败: ${e.message}",
                            showDeleteConfirm = false,
                            memoryToDelete = null
                        )
                    }
                }
            )
        }
    }
    
    /**
     * 取消删除
     */
    fun cancelDelete() {
        _uiState.update { 
            it.copy(
                showDeleteConfirm = false,
                memoryToDelete = null
            )
        }
    }

    /**
     * 打开记忆详情弹窗，同时拉取它的关联邻域。
     *
     * 关联里点另一条记忆也走这里：弹窗原地换内容，等同在图里走一步。
     */
    fun openMemoryDetail(memory: Memory) {
        _uiState.update { it.copy(showMemoryDetail = true, selectedMemory = memory) }
        graphCoordinator.loadRelations(memory.id, currentProfileFilename)
    }

    /**
     * 关闭记忆详情弹窗
     */
    fun closeMemoryDetail() {
        graphCoordinator.clearRelations()
        _uiState.update { it.copy(showMemoryDetail = false, selectedMemory = null) }
    }

    /** 进入记忆网络：加载地标层（已加载过则复用） */
    fun loadGraphAnchors() {
        graphCoordinator.loadAnchors(currentProfileFilename)
    }

    /** 展开某个地标的邻域 */
    fun openGraphAnchor(anchorId: String) {
        graphCoordinator.openAnchor(anchorId, currentProfileFilename)
    }

    /** 从邻域退回地标层 */
    fun closeGraphAnchor() {
        graphCoordinator.backToAnchors()
    }

    /** 失败重试当前层 */
    fun retryGraph() {
        graphCoordinator.retry(currentProfileFilename)
    }
    
    /**
     * 切换重要标记
     */
    fun toggleImportant(memory: Memory) {
        viewModelScope.launch {
            val result = memoryRepository.markImportant(memory.id, !memory.isImportant)
            
            result.fold(
                onSuccess = {
                    _uiState.update { state ->
                        state.copy(
                            memories = state.memories.map { m ->
                                if (m.id == memory.id) {
                                    m.copy(isImportant = !m.isImportant)
                                } else m
                            }
                        )
                    }
                    loadStats()
                },
                onFailure = { e ->
                    _uiState.update { it.copy(error = "操作失败: ${e.message}") }
                }
            )
        }
    }
    
    /**
     * 清除错误
     */
    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }
    
    /**
     * 清除过滤
     */
    fun clearFilters() {
        _uiState.update {
            it.copy(
                searchQuery = "",
                selectedTopic = null,
                showImportantOnly = false
            )
        }
        loadMemories()
    }
}
