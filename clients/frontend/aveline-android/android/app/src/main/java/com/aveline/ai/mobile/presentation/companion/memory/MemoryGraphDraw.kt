package com.aveline.ai.mobile.presentation.companion.memory

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.sin

// ── 画布上的颜色与字号（全部来自设计稿的取值）──
private val RingColor = Color(0x12FFFFFF)      // 三圈虚线环：7% 白
private val SectorLineColor = Color(0x0AFFFFFF) // 六条扇区分隔线：4% 白
private val SectorLabelColor = Color(0xFF5C5B57)
private val AnchorMetaColor = Color(0xFF82817C)
private val AnchorTitleColor = Color(0xFFCFCEC9)
private const val DIMMED_NODE_ALPHA = 0.22f

private const val LABEL_FONT = 10.5f
private const val LABEL_FONT_STRONG = 12f
private const val LABEL_OUTLINE_WIDTH = 3f

/** 布局层刻意用纯 JVM 的 [GraphPoint] 便于单测，画到 Compose 画布时再转 [Offset] */
internal fun GraphPoint.toOffset(): Offset = Offset(x, y)

/**
 * 画一整张记忆网络。
 *
 * 顺序不能变：罗盘在最底下、边在节点下、字在最上面。
 * 所有绘制逻辑集中在这个文件，[MemoryGraphCanvas] 只负责测量、手势与视口变换。
 */
internal fun DrawScope.drawMemoryGraph(
    placement: GraphPlacement,
    isAnchorLayer: Boolean,
    seedId: String?,
    selectedId: String?,
    neighbors: Set<String>,
    centerCount: Int?,
    colorOf: (String) -> Color,
    labelOf: (String) -> GraphLabel?,
    measurer: TextMeasurer
) {
    drawCompass(placement = placement, isAnchorLayer = isAnchorLayer)
    drawSectorLabels(placement = placement, isAnchorLayer = isAnchorLayer, measurer = measurer)
    drawEdges(placement = placement, selectedId = selectedId)
    drawNodes(
        placement = placement,
        colorOf = colorOf,
        selectedId = selectedId,
        neighbors = neighbors
    )
    if (isAnchorLayer && centerCount != null) {
        drawCenterCaption(placement = placement, total = centerCount, measurer = measurer)
    }
    drawLabels(
        placement = placement,
        isAnchorLayer = isAnchorLayer,
        seedId = seedId,
        selectedId = selectedId,
        neighbors = neighbors,
        labelOf = labelOf,
        measurer = measurer
    )
}

/** 三圈虚线环（1 / 2 / 3 跳）；地标层只有一圈轨道 */
private fun DrawScope.drawCompass(placement: GraphPlacement, isAnchorLayer: Boolean) {
    val radius = placement.compassRadius
    if (radius <= 0f) return
    val center = placement.center.toOffset()
    val dash = PathEffect.dashPathEffect(floatArrayOf(2f, 5f))

    if (isAnchorLayer) {
        drawCircle(
            color = RingColor,
            radius = radius,
            center = center,
            style = Stroke(width = 1f, pathEffect = dash)
        )
        return
    }

    MemoryGraphLayout.RING_RATIOS.forEach { ratio ->
        drawCircle(
            color = RingColor,
            radius = radius * ratio,
            center = center,
            style = Stroke(width = 1f, pathEffect = dash)
        )
    }

    val sectorWidth = 2f * PI.toFloat() / MemoryGraphLayout.SECTORS.size
    MemoryGraphLayout.SECTORS.indices.forEach { index ->
        val angle = -PI.toFloat() / 2f + index * sectorWidth
        drawLine(
            color = SectorLineColor,
            start = center + Offset(22f * cos(angle), 22f * sin(angle)),
            end = center + Offset((radius + 6f) * cos(angle), (radius + 6f) * sin(angle)),
            strokeWidth = 1f
        )
    }
}

/** 外圈扇区名：事件 / 对话 / 后续 / 前因 / 相关 / 话题 */
private fun DrawScope.drawSectorLabels(
    placement: GraphPlacement,
    isAnchorLayer: Boolean,
    measurer: TextMeasurer
) {
    val radius = placement.compassRadius
    if (isAnchorLayer || radius <= 0f) return
    val center = placement.center.toOffset()
    val sectorWidth = 2f * PI.toFloat() / MemoryGraphLayout.SECTORS.size
    val style = TextStyle(fontSize = 10.5.sp, color = SectorLabelColor)

    MemoryGraphLayout.SECTOR_LABELS.forEachIndexed { index, label ->
        val angle = -PI.toFloat() / 2f + index * sectorWidth + sectorWidth / 2f
        val x = center.x + (radius + 16f) * cos(angle)
        val y = center.y + (radius + 16f) * sin(angle) + 4f
        val layout = measurer.measure(label, style = style)
        drawText(
            textLayoutResult = layout,
            topLeft = Offset(x - layout.size.width / 2f, y - layout.size.height / 2f)
        )
    }
}

/** 边：和文字同色的浅色；选中时相连的边亮、其余几乎消失 */
private fun DrawScope.drawEdges(placement: GraphPlacement, selectedId: String?) {
    // 边数可达几十条，先建一次 id → 坐标的映射，避免每条边都线性找两个端点
    val centers = placement.nodes.associate { it.id to it.center.toOffset() }
    placement.edges.forEach { edge ->
        val from = centers[edge.sourceId] ?: return@forEach
        val to = centers[edge.targetId] ?: return@forEach
        val strength = edge.strength.coerceIn(0f, 1f)
        val touch = selectedId != null &&
            (edge.sourceId == selectedId || edge.targetId == selectedId)
        val alpha = when {
            selectedId == null -> 0.10f + strength * 0.25f
            touch -> 0.6f
            else -> 0.04f
        }
        drawLine(
            color = TextPrimary.copy(alpha = alpha),
            start = from,
            end = to,
            strokeWidth = 0.8f + strength * 1.2f
        )
    }
}

/** 节点：选中时只留它、中心和一跳邻居，其余降到 22% */
private fun DrawScope.drawNodes(
    placement: GraphPlacement,
    colorOf: (String) -> Color,
    selectedId: String?,
    neighbors: Set<String>
) {
    placement.nodes.forEach { node ->
        val dim = selectedId != null && node.id != selectedId && node.id !in neighbors
        val alpha = if (dim) DIMMED_NODE_ALPHA else 1f
        val center = node.center.toOffset()

        drawCircle(
            color = colorOf(node.id).copy(alpha = 0.85f * alpha),
            radius = node.radius,
            center = center
        )
        if (node.isSeed || node.id == selectedId) {
            drawCircle(
                color = TextPrimary.copy(alpha = 0.85f * alpha),
                radius = node.radius + 4f,
                center = center,
                style = Stroke(width = 1.4f)
            )
        }
    }
}

/** 地标层中心：总条数 + 「条记忆」 */
private fun DrawScope.drawCenterCaption(
    placement: GraphPlacement,
    total: Int,
    measurer: TextMeasurer
) {
    val center = placement.center.toOffset()
    val numberStyle = TextStyle(fontSize = 30.sp, color = TextPrimary, fontWeight = FontWeight.Medium)
    val unitStyle = TextStyle(fontSize = 12.sp, color = TextTertiary)

    val number = measurer.measure("$total", style = numberStyle)
    drawText(
        textLayoutResult = number,
        topLeft = Offset(center.x - number.size.width / 2f, center.y - number.size.height / 2f - 8f)
    )
    val unit = measurer.measure("条记忆", style = unitStyle)
    drawText(
        textLayoutResult = unit,
        topLeft = Offset(center.x - unit.size.width / 2f, center.y + 12f)
    )
}

/**
 * 标签。
 *
 * - 地标层：话题名 + 「日期 · N 条」两行，居中放在球下方；
 * - 邻域层：沿半径朝外放（左右两侧左/右对齐，上下居中），按「中心 → 选中 → 一跳邻居」
 *   的顺序贪心放置，和已放标签重叠就跳过——宁可少画几个字，也不能糊成一团。
 */
private fun DrawScope.drawLabels(
    placement: GraphPlacement,
    isAnchorLayer: Boolean,
    seedId: String?,
    selectedId: String?,
    neighbors: Set<String>,
    labelOf: (String) -> GraphLabel?,
    measurer: TextMeasurer
) {
    if (isAnchorLayer) {
        drawAnchorLabels(placement = placement, labelOf = labelOf, measurer = measurer)
        return
    }

    val visible = placement.nodes.filter { node ->
        val label = labelOf(node.id) ?: return@filter false
        label.text.isNotBlank() && when {
            selectedId == null -> true
            else -> node.id == selectedId || node.id == seedId || node.id in neighbors
        }
    }
    if (visible.isEmpty()) return

    val ordered = visible.sortedWith(
        compareBy(
            { if (it.isSeed) 0 else 1 },
            { if (it.id == selectedId) 0 else 1 },
            { it.ring },
            { -it.radius }
        )
    )

    val center = placement.center.toOffset()
    val placed = mutableListOf<Rect>()

    ordered.forEach { node ->
        val label = labelOf(node.id) ?: return@forEach
        val strong = node.isSeed || node.id == selectedId
        val fontSize = if (strong) LABEL_FONT_STRONG else LABEL_FONT
        val gap = node.radius + if (strong) 12f else 9f

        val layout = measurer.measure(
            label.text,
            style = TextStyle(
                fontSize = fontSize.sp,
                color = if (strong) TextPrimary else TextSecondary,
                fontWeight = if (strong) FontWeight.Medium else FontWeight.Normal
            )
        )
        val width = layout.size.width.toFloat()
        val height = layout.size.height.toFloat()

        val dx = node.center.x - center.x
        val dy = node.center.y - center.y
        val length = hypot(dx, dy).takeIf { it > 0.01f } ?: 1f
        val ux = dx / length
        val uy = dy / length

        val left: Float
        val top: Float
        if (abs(ux) > 0.55f) {
            left = if (ux > 0) node.center.x + gap else node.center.x - gap - width
            top = node.center.y - height / 2f
        } else {
            left = node.center.x - width / 2f
            top = if (uy > 0) node.center.y + gap else node.center.y - gap - height
        }

        val box = Rect(left - 2f, top - 1f, left + width + 2f, top + height + 1f)
        val outside = box.left < 0f || box.right > size.width || box.top < 0f || box.bottom > size.height
        if (!strong && (outside || placed.any { it.overlaps(box) })) return@forEach
        placed.add(box)

        drawLabelLine(
            text = label.text,
            topLeft = Offset(left, top),
            fontSize = fontSize,
            color = if (strong) TextPrimary else TextSecondary,
            align = TextAlign.Left,
            bold = strong,
            measurer = measurer
        )
    }
}

/** 地标层：两行居中标签，标题在上、日期 · 条数在下 */
private fun DrawScope.drawAnchorLabels(
    placement: GraphPlacement,
    labelOf: (String) -> GraphLabel?,
    measurer: TextMeasurer
) {
    placement.nodes.forEach { node ->
        val label = labelOf(node.id) ?: return@forEach
        val center = node.center.toOffset()
        drawLabelLine(
            text = label.text,
            topLeft = Offset(center.x, center.y + node.radius + 15f),
            fontSize = 11.5f,
            color = AnchorTitleColor,
            align = TextAlign.Center,
            measurer = measurer
        )
        label.meta?.let { meta ->
            drawLabelLine(
                text = meta,
                topLeft = Offset(center.x, center.y + node.radius + 29f),
                fontSize = 10f,
                color = AnchorMetaColor,
                align = TextAlign.Center,
                measurer = measurer
            )
        }
    }
}

/**
 * 画一行带描边的字。
 *
 * 描边用页面背景色（3px）而不是黑：节点球和连线都在字的下面，
 * 没有这层描边时稍长一点的标签会被边线横穿，读不出来。
 */
private fun DrawScope.drawLabelLine(
    text: String,
    topLeft: Offset,
    fontSize: Float,
    color: Color,
    align: TextAlign,
    measurer: TextMeasurer,
    bold: Boolean = false
) {
    val style = TextStyle(
        fontSize = fontSize.sp,
        color = color,
        textAlign = align,
        fontWeight = if (bold) FontWeight.Medium else FontWeight.Normal
    )
    val fill = measurer.measure(text, style = style)
    val originX = if (align == TextAlign.Center) topLeft.x - fill.size.width / 2f else topLeft.x
    val origin = Offset(originX, topLeft.y)
    val outline = measurer.measure(
        text,
        style = style.copy(color = Background, drawStyle = Stroke(width = LABEL_OUTLINE_WIDTH))
    )
    drawText(textLayoutResult = outline, topLeft = origin)
    drawText(textLayoutResult = fill, topLeft = origin)
}
