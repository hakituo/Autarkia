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
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * 记忆管理 ViewModel
 * 
 * 功能：
 * - 记忆列表加载和刷新
 * - 搜索和过滤
 * - 删除和标记重要
 * 
 * Requirements: 9.1, 9.2, 9.3
 */
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

    /** 当前正在查看的 persona 文件名（来自聊天会话/伴侣面板选择，纯只读）；为 null 表示用后端默认 */
    @Volatile
    private var currentProfileFilename: String? = null

    /** 当前聊天会话 id；聊天记录树的数据源，纯只读 */
    @Volatile
    private var currentSessionId: String? = null

    private var conversationJob: Job? = null

    /** 首轮记忆列表 / 统计 / 标签是否已经拉过（避免按 null persona 白拉一轮）。 */
    private var initialLoadStarted = false

    /**
     * 首次加载（幂等）。
     *
     * 以前在 init 里先按 null persona 拉一轮，等 ChatScreen 注入 persona 后再整轮重拉，
     * 6 个请求里有一半是白发的。现在改成"谁先确定上下文谁触发"：
     * - 聊天页进页时 [setViewingPersona] 直接带 persona 拉一次；
     * - 深链只给 role 没给 persona 时，详情面板打开会调 [ensureLoaded] 兜底。
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
     *
     * 与 setViewingPersona 一样是只读注入：只切数据源，不切换聊天会话本身。
     */
    fun setViewingSession(sessionId: String?) {
        val target = sessionId?.trim().orEmpty().ifBlank { null }
        if (target == currentSessionId) return
        currentSessionId = target
        conversationJob?.cancel()
        conversationJob = null

        if (target == null) {
            _uiState.update {
                it.copy(conversationMessages = emptyList(), remoteConversationMessages = emptyList())
            }
            return
        }

        conversationJob = viewModelScope.launch(Dispatchers.IO) {
            // 本地消息树先上屏；服务端历史随后补进来，断网时只显示本地部分。
            launch {
                chatRepository.observeAllMessages(target)
                    .catch { e -> Log.w(TAG, "聊天记录树订阅失败: ${e.message}") }
                    .collect { messages ->
                        _uiState.update { it.copy(conversationMessages = messages) }
                    }
            }
            val remote = chatRepository.fetchRemoteHistory(target).getOrElse { emptyList() }
            _uiState.update { it.copy(remoteConversationMessages = remote) }
        }
    }

    /**
     * 加载记忆列表
     */
    fun loadMemories() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }

            // 类型 / 话题 / 重要筛选全部在客户端完成：后端只支持 category 过滤，
            // 而历史记忆的 category 基本是 uncategorized，按类型请求会直接把列表筛空。
            val result = memoryRepository.getMemories(
                MemoryFilter(),
                _uiState.value.sortOrder,
                persona = currentProfileFilename
            )

            _uiState.update {
                it.copy(
                    memories = result,
                    isLoading = false
                )
            }
        }
    }

    /**
     * 加载统计信息
     */
    private fun loadStats() {
        viewModelScope.launch {
            val stats = memoryRepository.getMemoryStats(persona = currentProfileFilename)
            _uiState.update { it.copy(stats = stats) }
        }
    }

    /**
     * 加载标签列表
     */
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
        
        if (query.isBlank()) {
            loadMemories()
            return
        }
        
        searchJob = viewModelScope.launch {
            delay(searchDebounceMs)
            
            _uiState.update { it.copy(isLoading = true) }
            
            val results = memoryRepository.searchMemories(query, persona = currentProfileFilename)
            
            _uiState.update { 
                it.copy(
                    memories = results,
                    isLoading = false
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
     * 设置排序方式
     */
    fun setSortOrder(order: MemorySortOrder) {
        _uiState.update { it.copy(sortOrder = order) }
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
