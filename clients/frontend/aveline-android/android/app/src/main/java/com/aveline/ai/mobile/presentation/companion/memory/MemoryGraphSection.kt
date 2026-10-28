package com.aveline.ai.mobile.presentation.companion.memory

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.Memory
import com.aveline.ai.mobile.presentation.memory.MemoryGraphUiState
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.TextTertiary

private val FallbackNodeColor = Color(0xFFB0B8C0)

/**
 * 记忆网络：地标层 → 点开某个地标的邻域。
 *
 * 不用力导向、不用树：地标是一圈稳定的入口，展开后按关系类型分扇区、
 * 按跳数分环，同一份数据每次都画在同一个位置，用户才能记住「那件事在哪」。
 *
 * 点节点不再直接弹详情：先高亮它和它的一跳邻居，底部浮出预览卡，
 * 再点「看全文」才打开详情面板。这样在图上连着看几条记忆时不用来回开关弹窗。
 *
 * @param state 图谱状态（含地标 / 子图 / 加载与错误）
 * @param onEnter 首次进入该视图时触发，用于加载地标
 * @param onAnchorClick 点击地标，展开它的邻域
 * @param onNodeClick 点击预览卡里的「看全文」，打开记忆详情
 * @param onRecenter 以某条记忆为中心重画（复用 onAnchorClick）
 * @param onBack 从邻域退回地标层
 * @param onRetry 失败重试当前层
 */
@Composable
internal fun MemoryGraphSection(
    state: MemoryGraphUiState,
    onEnter: () -> Unit,
    onAnchorClick: (String) -> Unit,
    onNodeClick: (Memory) -> Unit,
    onRecenter: (String) -> Unit,
    onBack: () -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier
) {
    LaunchedEffect(Unit) { onEnter() }

    val isAnchorLayer = !state.isExpanded
    var selectedId by remember { mutableStateOf<String?>(null) }
    // 换中心或回地标层时清掉选中，否则预览卡会挂在上一次的点上
    LaunchedEffect(state.seedId, isAnchorLayer) { selectedId = null }

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

    // 选中节点的一跳邻居：决定哪些边变亮、哪些节点保持亮、哪些标签继续显示
    val neighbors = remember(selectedId, state.graph) {
        val target = selectedId
        if (target == null) {
            emptySet()
        } else {
            state.graph.edges
                .asSequence()
                .filter { it.sourceId == target || it.targetId == target }
                .flatMap { sequenceOf(it.sourceId, it.targetId) }
                .toSet()
        }
    }
    val selectedRelation = remember(selectedId, state.graph) {
        state.graph.nodes.firstOrNull { it.memory.id == selectedId }
    }

    val labels = remember(isAnchorLayer, state.anchors, state.graph, state.seedId) {
        if (isAnchorLayer) {
            state.anchors.associate { anchor ->
                anchor.memory.id to anchorLabel(anchor.title, anchor.memberCount)
            }
        } else {
            state.graph.nodes.associate { node ->
                node.memory.id to GraphLabel(
                    text = previewLabel(
                        text = node.preview,
                        limit = if (node.memory.id == state.seedId) SEED_LABEL_LIMIT else LABEL_LIMIT
                    )
                )
            }
        }
    }
    val totalCount = remember(state.anchors) { state.anchors.sumOf { it.memberCount } }

    Column(modifier = modifier.fillMaxSize()) {
        GraphHeader(
            isAnchorLayer = isAnchorLayer,
            anchorCount = state.anchors.size,
            crumb = state.anchors.firstOrNull { it.memory.id == state.seedId }?.title.orEmpty(),
            nodeCount = state.graph.nodes.size,
            edgeCount = state.graph.edges.size,
            onBack = onBack
        )

        Box(modifier = Modifier.fillMaxWidth().weight(1f)) {
            when {
                state.isLoadingAnchors || state.isLoadingGraph -> Box(
                    modifier = Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator(
                        color = Accent,
                        modifier = Modifier.size(24.dp),
                        strokeWidth = 2.dp
                    )
                }

                canvasNodes.isEmpty() -> Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(vertical = 32.dp),
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

                else -> {
                    MemoryGraphCanvas(
                        nodes = canvasNodes,
                        edges = canvasEdges,
                        seedId = state.seedId,
                        isAnchorLayer = isAnchorLayer,
                        centerCount = if (isAnchorLayer) totalCount else null,
                        colorOf = { id ->
                            memories[id]?.let { memoryTopicColor(it.topicKey) } ?: FallbackNodeColor
                        },
                        labelOf = { id -> labels[id] },
                        selectedId = selectedId,
                        neighbors = neighbors,
                        onNodeClick = { id ->
                            when {
                                id == null -> selectedId = null
                                isAnchorLayer -> onAnchorClick(id)
                                else -> selectedId = if (selectedId == id) null else id
                            }
                        },
                        modifier = Modifier.fillMaxSize()
                    )

                    if (!isAnchorLayer && selectedId == null) {
                        Text(
                            text = "点节点看内容 · 双指缩放 · 拖动",
                            style = MaterialTheme.typography.bodySmall.copy(fontSize = 11.5.sp),
                            color = TextTertiary.copy(alpha = 0.7f),
                            modifier = Modifier
                                .align(Alignment.BottomCenter)
                                .padding(bottom = 14.dp)
                        )
                    }

                    if (!isAnchorLayer && selectedRelation != null) {
                        MemoryGraphPreviewCard(
                            relation = selectedRelation,
                            onOpen = { onNodeClick(selectedRelation.memory) },
                            onRecenter = {
                                onRecenter(selectedRelation.memory.id)
                                selectedId = null
                            },
                            modifier = Modifier
                                .align(Alignment.BottomCenter)
                                .fillMaxWidth()
                                .padding(bottom = 6.dp)
                        )
                    }
                }
            }

            if (state.error != null && canvasNodes.isNotEmpty()) {
                Text(
                    text = state.error,
                    style = MaterialTheme.typography.bodySmall.copy(fontSize = 11.5.sp),
                    color = TextTertiary,
                    modifier = Modifier
                        .align(Alignment.TopCenter)
                        .padding(top = 6.dp)
                )
            }
        }
    }
}
