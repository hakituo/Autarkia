package com.aveline.ai.mobile.presentation.memory

import com.aveline.ai.mobile.domain.models.MemoryAnchor
import com.aveline.ai.mobile.domain.models.MemoryGraph
import com.aveline.ai.mobile.domain.models.MemoryRelation
import com.aveline.ai.mobile.domain.repository.MemoryRepository
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 记忆网络（图谱）UI 状态。
 *
 * @property anchors 地标层：某天 × 某话题压成的一簇记忆
 * @property graph 当前展开的子图（回到地标层时为空图）
 * @property seedId 当前中心记忆；为空表示停在地标层
 * @property relations 详情弹窗的「想起…」列表
 * @property relationsForId 上面这份关系属于哪条记忆，用于丢弃过期结果
 */
data class MemoryGraphUiState(
    val anchors: List<MemoryAnchor> = emptyList(),
    val graph: MemoryGraph = MemoryGraph(),
    val seedId: String? = null,
    val relations: List<MemoryRelation> = emptyList(),
    val relationsForId: String? = null,
    val isLoadingAnchors: Boolean = false,
    val isLoadingGraph: Boolean = false,
    val isLoadingRelations: Boolean = false,
    val error: String? = null
) {
    /** 是否已经进入某个地标的邻域 */
    val isExpanded: Boolean
        get() = seedId != null
}

/**
 * 记忆网络的加载器。
 *
 * 关系/地标/子图三条链路都有自己的请求与取消逻辑，放在 ViewModel 里会把
 * 列表管理那一摊搅在一起；这里独立成一个职责单元，ViewModel 只做转发。
 */
class MemoryGraphCoordinator(
    private val repository: MemoryRepository,
    private val scope: CoroutineScope,
    private val dispatcher: CoroutineDispatcher = Dispatchers.IO
) {

    private val _state = MutableStateFlow(MemoryGraphUiState())
    val state: StateFlow<MemoryGraphUiState> = _state.asStateFlow()

    private var anchorsJob: Job? = null
    private var graphJob: Job? = null
    private var relationsJob: Job? = null

    /** 加载地标层；已加载过就复用，除非显式 force */
    fun loadAnchors(persona: String?, force: Boolean = false) {
        val current = _state.value
        if (!force && (current.anchors.isNotEmpty() || current.isLoadingAnchors)) return
        anchorsJob?.cancel()
        _state.update { it.copy(isLoadingAnchors = true, error = null) }
        anchorsJob = scope.launch(dispatcher) {
            val anchors = repository.getMemoryAnchors(persona)
            _state.update {
                it.copy(
                    anchors = anchors,
                    isLoadingAnchors = false,
                    error = if (anchors.isEmpty()) "还没有可以汇成地标的记忆" else null
                )
            }
        }
    }

    /** 展开某个地标的邻域；失败或没有连出关系时退回地标层 */
    fun openAnchor(anchorId: String, persona: String?) {
        val target = anchorId.trim()
        if (target.isEmpty() || _state.value.seedId == target) return
        graphJob?.cancel()
        _state.update {
            it.copy(seedId = target, graph = MemoryGraph(), isLoadingGraph = true, error = null)
        }
        graphJob = scope.launch(dispatcher) {
            val graph = repository.getMemoryGraph(target, persona)
            if (_state.value.seedId != target) return@launch
            _state.update {
                if (graph.isEmpty) {
                    it.copy(
                        seedId = null,
                        graph = MemoryGraph(),
                        isLoadingGraph = false,
                        error = "这段记忆还没连出关系"
                    )
                } else {
                    it.copy(graph = graph, isLoadingGraph = false)
                }
            }
        }
    }

    /** 退回地标层 */
    fun backToAnchors() {
        graphJob?.cancel()
        graphJob = null
        _state.update {
            it.copy(seedId = null, graph = MemoryGraph(), isLoadingGraph = false)
        }
    }

    /** 重试当前层：在地标层就重拉地标，在邻域里就重拉子图 */
    fun retry(persona: String?) {
        val seed = _state.value.seedId
        if (seed == null) {
            loadAnchors(persona, force = true)
        } else {
            _state.update { it.copy(seedId = null) }
            openAnchor(seed, persona)
        }
    }

    /** 拉取详情弹窗的「想起…」；失败时只留空列表 */
    fun loadRelations(memoryId: String, persona: String?) {
        val target = memoryId.trim()
        if (target.isEmpty()) return
        relationsJob?.cancel()
        _state.update {
            it.copy(relations = emptyList(), relationsForId = target, isLoadingRelations = true)
        }
        relationsJob = scope.launch(dispatcher) {
            val relations = repository.getMemoryRelations(target, persona)
            if (_state.value.relationsForId != target) return@launch
            _state.update {
                it.copy(relations = relations, isLoadingRelations = false)
            }
        }
    }

    /** 关闭详情弹窗时清空关系，避免下次打开先闪一眼上一条的邻居 */
    fun clearRelations() {
        relationsJob?.cancel()
        relationsJob = null
        _state.update {
            it.copy(relations = emptyList(), relationsForId = null, isLoadingRelations = false)
        }
    }

    /** 切换角色时整体重置：地标是分角色算的，不能复用 */
    fun reset() {
        anchorsJob?.cancel()
        graphJob?.cancel()
        relationsJob?.cancel()
        anchorsJob = null
        graphJob = null
        relationsJob = null
        _state.value = MemoryGraphUiState()
    }
}
