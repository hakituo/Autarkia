package com.aveline.ai.mobile.presentation.companion.memory

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.rememberTextMeasurer

/** 节点标签：正文一行，地标层再加一行日期 · 条数 */
internal data class GraphLabel(val text: String, val meta: String? = null)

/**
 * 记忆网络的画布。
 *
 * 布局是确定性的（见 [MemoryGraphLayout]）：同样的数据每次都画在同一位置，
 * 用户才能形成空间记忆。手势只做双指缩放与拖动，点击命中节点后回调。
 *
 * 这一版把「罗盘」真正画了出来：三圈 2/5 虚线环表示 1/2/3 跳，六条极淡的扇区线，
 * 外圈标上扇区名。之前这三样在布局里都存在，却没有任何一处往下传，画面上只剩一堆球。
 *
 * 具体的绘制在 [drawMemoryGraph] 里，本文件只负责测量、手势与视口变换。
 *
 * @param nodes 参与布局的节点
 * @param edges 边（两端必须都在 [nodes] 里，布局阶段会再过滤一次）
 * @param seedId 中心记忆；地标层传 null
 * @param isAnchorLayer true 画地标环，false 画以 [seedId] 为中心的同心环
 * @param centerCount 地标层中心要显示的总条数；邻域层传 null
 * @param colorOf 节点 id → 主题色
 * @param labelOf 节点 id → 标签，返回 null 则不画字
 * @param selectedId 当前选中的节点
 * @param neighbors 选中节点的一跳邻居（决定谁保持亮、谁继续显示标签）
 * @param onNodeClick 点击节点回调；点空白处传 null
 */
@Composable
internal fun MemoryGraphCanvas(
    nodes: List<GraphNodeInput>,
    edges: List<GraphEdgeInput>,
    seedId: String?,
    isAnchorLayer: Boolean,
    centerCount: Int?,
    colorOf: (String) -> Color,
    labelOf: (String) -> GraphLabel?,
    selectedId: String?,
    neighbors: Set<String>,
    onNodeClick: (String?) -> Unit,
    modifier: Modifier = Modifier
) {
    val density = LocalDensity.current
    val scaleState = remember { mutableFloatStateOf(1f) }
    val offsetState = remember { mutableStateOf(Offset.Zero) }

    // 换图（换中心 / 回地标层）时复位视口，避免停在上一次的偏移里
    LaunchedEffect(seedId, isAnchorLayer) {
        scaleState.floatValue = 1f
        offsetState.value = Offset.Zero
    }

    val textMeasurer = rememberTextMeasurer()

    BoxWithConstraints(modifier = modifier) {
        val widthPx = with(density) { maxWidth.toPx() }
        val heightPx = with(density) { maxHeight.toPx() }
        val center = Offset(widthPx / 2f, heightPx / 2f)
        val placement = remember(nodes, edges, seedId, isAnchorLayer, widthPx, heightPx) {
            if (isAnchorLayer) {
                MemoryGraphLayout.anchors(nodes, widthPx, heightPx)
            } else {
                MemoryGraphLayout.neighborhood(nodes, edges, seedId, widthPx, heightPx)
            }
        }

        Canvas(
            modifier = Modifier
                .fillMaxSize()
                .pointerInput(placement) {
                    detectTapGestures { tap ->
                        val scale = scaleState.floatValue
                        val offset = offsetState.value
                        val localX = (tap.x - center.x - offset.x) / scale + center.x
                        val localY = (tap.y - center.y - offset.y) / scale + center.y
                        onNodeClick(placement.nodeAt(localX, localY))
                    }
                }
                .pointerInput(Unit) {
                    detectTransformGestures { _, pan, zoom, _ ->
                        scaleState.floatValue =
                            (scaleState.floatValue * zoom).coerceIn(0.7f, 2.8f)
                        offsetState.value += pan
                    }
                }
        ) {
            withTransform({
                translate(offsetState.value.x, offsetState.value.y)
                scale(scaleState.floatValue, scaleState.floatValue, pivot = center)
            }) {
                drawMemoryGraph(
                    placement = placement,
                    isAnchorLayer = isAnchorLayer,
                    seedId = seedId,
                    selectedId = selectedId,
                    neighbors = neighbors,
                    centerCount = centerCount,
                    colorOf = colorOf,
                    labelOf = labelOf,
                    measurer = textMeasurer
                )
            }
        }
    }
}
