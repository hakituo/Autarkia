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
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.sp

private val EdgeColor = Color(0xFF5E7385)

/**
 * 记忆网络的画布。
 *
 * 布局是确定性的（见 [MemoryGraphLayout]）：同样的数据每次都画在同一位置，
 * 用户才能形成空间记忆。手势只做双指缩放与拖动，点击命中节点后回调。
 *
 * @param nodes 参与布局的节点
 * @param edges 边（两端必须都在 [nodes] 里，布局阶段会再过滤一次）
 * @param seedId 中心记忆；地标层传 null
 * @param isAnchorLayer true 画地标环，false 画以 [seedId] 为中心的同心环
 * @param colorOf 节点 id → 主题色
 * @param labelOf 节点 id → 标签，返回 null 则不画字
 * @param onNodeClick 点击节点回调
 */
@Composable
internal fun MemoryGraphCanvas(
    nodes: List<GraphNodeInput>,
    edges: List<GraphEdgeInput>,
    seedId: String?,
    isAnchorLayer: Boolean,
    colorOf: (String) -> Color,
    labelOf: (String) -> String?,
    onNodeClick: (String) -> Unit,
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
        val centers = remember(placement) {
            placement.nodes.associate { it.id to it.center }
        }
        val textMeasurer = rememberTextMeasurer()
        val labelStyle = remember {
            TextStyle(fontSize = 9.sp, color = Color(0xFF35424C), fontWeight = FontWeight.Medium)
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
                        placement.nodeAt(localX, localY)?.let(onNodeClick)
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
                placement.edges.forEach { edge ->
                    val from = centers[edge.sourceId] ?: return@forEach
                    val to = centers[edge.targetId] ?: return@forEach
                    val strength = edge.strength.coerceIn(0f, 1f)
                    drawLine(
                        color = EdgeColor.copy(alpha = 0.16f + strength * 0.30f),
                        start = from,
                        end = to,
                        strokeWidth = 1f + strength * 1.6f
                    )
                }
                placement.nodes.forEach { node ->
                    val color = colorOf(node.id)
                    drawCircle(
                        color = color.copy(alpha = 0.82f),
                        radius = node.radius,
                        center = node.center
                    )
                    if (node.isSeed) {
                        drawCircle(
                            color = color,
                            radius = node.radius + 4f,
                            center = node.center,
                            style = Stroke(width = 2.2f)
                        )
                    }
                }
                placement.nodes.forEach { node ->
                    val label = labelOf(node.id) ?: return@forEach
                    val layout = textMeasurer.measure(label, style = labelStyle)
                    drawText(
                        textLayoutResult = layout,
                        topLeft = Offset(
                            node.center.x - layout.size.width / 2f,
                            node.center.y + node.radius + 6f
                        )
                    )
                }
            }
        }
    }
}
