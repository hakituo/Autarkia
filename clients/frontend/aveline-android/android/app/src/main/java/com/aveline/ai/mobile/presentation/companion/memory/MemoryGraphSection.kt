package com.aveline.ai.mobile.presentation.companion.memory

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.Memory
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.memory.MemoryGraphUiState
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.TextTertiary

private const val GRAPH_HEIGHT_DP = 340
private const val MAX_LABELS = 6
private val FallbackNodeColor = Color(0xFF94A3B8)

/**
 * 记忆网络：地标层 → 点开某个地标的邻域。
 *
 * 不用力导向、不用树：地标是一圈稳定的入口，展开后按关系类型分扇区、
 * 按跳数分环，同一份数据每次都画在同一个位置，用户才能记住「那件事在哪」。
 *
 * @param state 图谱状态（含地标 / 子图 / 加载与错误）
 * @param onEnter 首次进入该视图时触发，用于加载地标
 * @param onAnchorClick 点击地标，展开它的邻域
 * @param onNodeClick 点击邻域节点，打开记忆详情
 * @param onBack 从邻域退回地标层
 * @param onRetry 失败重试当前层
 */
@Composable
internal fun MemoryGraphSection(
    state: MemoryGraphUiState,
    onEnter: () -> Unit,
    onAnchorClick: (String) -> Unit,
    onNodeClick: (Memory) -> Unit,
    onBack: () -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier
) {
    LaunchedEffect(Unit) { onEnter() }

    val isAnchorLayer = !state.isExpanded
    val memories = remember(isAnchorLayer, state.anchors, state.graph) {
        if (isAnchorLayer) {
            state.anchors.associate { it.memory.id to it.memory }
        } else {
            state.graph.nodes.associate { it.memory.id to it.memory }
        }
    }
    val canvasNodes = remember(isAnchorLayer, state.anchors, state.graph) {
        if (isAnchorLayer) {
            state.anchors.map { anchor ->
                GraphNodeInput(
                    id = anchor.memory.id,
                    relation = "anchor",
                    distance = 0,
                    weight = anchor.memory.importance.toFloat(),
                    memberCount = anchor.memberCount
                )
            }
        } else {
            state.graph.nodes.map { node ->
                GraphNodeInput(
                    id = node.memory.id,
                    relation = node.relation,
                    distance = node.distance,
                    weight = node.memory.importance.toFloat()
                )
            }
        }
    }
    val canvasEdges = remember(state.graph) {
        state.graph.edges.map { GraphEdgeInput(it.sourceId, it.targetId, it.strength) }
    }
    val labels = remember(isAnchorLayer, state.anchors, state.graph, state.seedId) {
        buildGraphLabels(isAnchorLayer, state)
    }

    SectionCard(
        title = if (isAnchorLayer) "记忆网络" else "这附近的记忆",
        subtitle = if (isAnchorLayer) {
            "球越大表示那段时间聊得越多，点一下展开"
        } else {
            "点节点看全文，双指缩放，可随时回到地标"
        },
        modifier = modifier
    ) {
        if (!isAnchorLayer) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = "${state.graph.nodes.size} 个节点 · ${state.graph.edges.size} 条关联",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextTertiary
                )
                TextButton(onClick = onBack) { Text("返回地标", color = Accent) }
            }
        }

        when {
            state.isLoadingAnchors || state.isLoadingGraph -> {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height((GRAPH_HEIGHT_DP / 2).dp),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator(color = Accent)
                }
            }

            canvasNodes.isEmpty() -> {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 28.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    Text(
                        text = state.error ?: "还没有可以汇成地标的记忆",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextTertiary
                    )
                    if (state.error != null) {
                        TextButton(onClick = onRetry) { Text("重试") }
                    }
                }
            }

            else -> {
                MemoryGraphCanvas(
                    nodes = canvasNodes,
                    edges = canvasEdges,
                    seedId = state.seedId,
                    isAnchorLayer = isAnchorLayer,
                    colorOf = { id ->
                        memories[id]?.let { memoryTopicColor(it.topicKey) } ?: FallbackNodeColor
                    },
                    labelOf = { id -> labels[id] },
                    onNodeClick = { id ->
                        val memory = memories[id]
                        if (memory != null) {
                            if (isAnchorLayer) onAnchorClick(id) else onNodeClick(memory)
                        }
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(GRAPH_HEIGHT_DP.dp)
                )
                if (state.error != null) {
                    Text(
                        text = state.error,
                        style = MaterialTheme.typography.labelSmall,
                        color = TextTertiary,
                        modifier = Modifier.padding(top = 4.dp)
                    )
                }
                Spacer(modifier = Modifier.height(4.dp))
            }
        }
    }
}

/**
 * 只给最值得读的几个节点画字：地标全画，邻域只画中心与最强的几个。
 * 全画会把 40 个节点糊成一片。
 */
private fun buildGraphLabels(
    isAnchorLayer: Boolean,
    state: MemoryGraphUiState
): Map<String, String> {
    if (isAnchorLayer) {
        return state.anchors.associate { it.memory.id to it.title }
    }
    val keep = state.graph.nodes
        .sortedByDescending { it.strength }
        .take(MAX_LABELS)
        .mapTo(HashSet()) { it.memory.id }
    state.seedId?.let { keep += it }
    return state.graph.nodes
        .filter { it.memory.id in keep }
        .associate { it.memory.id to it.preview.take(12) }
}
