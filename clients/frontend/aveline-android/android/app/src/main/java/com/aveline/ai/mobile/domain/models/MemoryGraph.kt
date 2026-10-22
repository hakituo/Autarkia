package com.aveline.ai.mobile.domain.models

/**
 * 记忆地标：某天围绕某个话题的一簇记忆。
 *
 * @property memory 代表记忆（片段里最显著的一条）
 * @property title 地标名，形如「10月18日 · 记忆系统」
 * @property memberCount 这一簇里的记忆条数
 */
data class MemoryAnchor(
    val memory: Memory,
    val title: String,
    val memberCount: Int
)

/**
 * 记忆网络里的一条边。
 *
 * 关系由后端 relation_graph 给出，客户端只用于画线与着色。
 */
data class MemoryGraphEdge(
    val sourceId: String,
    val targetId: String,
    val relation: String,
    val relationLabel: String,
    val strength: Float
)

/**
 * 一张有限大小的记忆子图。
 *
 * @property rootId 中心记忆；为空表示这是按显著度自动取种子的概览图
 * @property nodes 节点（含预览文本与关系说明）
 * @property edges 边，两端必定都在 [nodes] 里
 * @property truncated 是否因为节点上限被截断
 */
data class MemoryGraph(
    val rootId: String = "",
    val nodes: List<MemoryRelation> = emptyList(),
    val edges: List<MemoryGraphEdge> = emptyList(),
    val truncated: Boolean = false
) {
    val isEmpty: Boolean
        get() = nodes.isEmpty()
}
