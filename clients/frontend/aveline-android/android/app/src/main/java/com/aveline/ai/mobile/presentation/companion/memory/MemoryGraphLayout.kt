package com.aveline.ai.mobile.presentation.companion.memory

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * 记忆网络布局的纯计算，不依赖 Compose，便于 JVM 单测。
 *
 * 刻意不用力导向：
 * - 力导向每次打开位置都不同，用户建立不了空间记忆；
 * - 手机上几百个节点的力导向既费电又容易挤成一团。
 *
 * 改用「固定罗盘」——关系类型决定方位扇区，跳数决定环距，权重决定半径。
 * 同样的数据永远画出同一张图，用户才能记住「那件事在右上角」。
 */
internal data class GraphNodeInput(
    val id: String,
    val relation: String,
    val distance: Int,
    val weight: Float,
    val memberCount: Int = 1
)

internal data class GraphPoint(val x: Float, val y: Float)

/** 画线用的边：强度决定线宽与透明度 */
internal data class GraphEdgeInput(
    val sourceId: String,
    val targetId: String,
    val strength: Float
)

internal data class GraphPlacedNode(
    val id: String,
    val center: GraphPoint,
    val radius: Float,
    val isSeed: Boolean,
    val ring: Int
)

/**
 * 一次布局的完整结果。
 *
 * [center] 与 [compassRadius] 是给画布画「罗盘」用的：三圈虚线环、六条扇区分隔线
 * 和外圈扇区名都要靠这两个值确定位置。之前这两个数只存在于布局内部，
 * 画布拿不到，所以罗盘一直画不出来。
 */
internal data class GraphPlacement(
    val nodes: List<GraphPlacedNode>,
    val edges: List<GraphEdgeInput>,
    val center: GraphPoint = GraphPoint(0f, 0f),
    val compassRadius: Float = 0f
) {
    /** 命中测试：返回点击位置命中的节点 id，没命中返回 null */
    fun nodeAt(x: Float, y: Float, slop: Float = 10f): String? {
        var best: GraphPlacedNode? = null
        var bestDistance = Float.MAX_VALUE
        nodes.forEach { node ->
            val dx = x - node.center.x
            val dy = y - node.center.y
            val reach = node.radius + slop
            val distance = dx * dx + dy * dy
            if (distance <= reach * reach && distance < bestDistance) {
                best = node
                bestDistance = distance
            }
        }
        return best?.id
    }
}

internal object MemoryGraphLayout {

    /** 关系类型 → 方位扇区；未知关系落到最后一个扇区 */
    internal val SECTORS: List<String> =
        listOf("event", "turn", "continuation", "parent", "related", "topic")

    /** 扇区名（画在外圈，用户一眼能读出「它在后续方向的第二环」） */
    internal val SECTOR_LABELS: List<String> =
        listOf("事件", "对话", "后续", "前因", "相关", "话题")

    /** 第 1/2/3 跳的环半径占可用半径的比例 */
    internal val RING_RATIOS: List<Float> = listOf(0.46f, 0.74f, 0.96f)

    /** 画布边缘留白：从 18 加到 30，给外圈的扇区名留位置 */
    private const val EDGE_PADDING = 30f

    /** 地标层的轨道留白：52，同样是为了放得下两行标签 */
    private const val ANCHOR_ORBIT_PADDING = 52f

    private const val MIN_NODE_RADIUS = 5f
    private const val MAX_NODE_RADIUS = 13f
    private const val SEED_RADIUS_BONUS = 4f

    /**
     * 以 [seedId] 为中心的邻域布局：中心 + 三个同心环，环内按关系扇区排布。
     */
    fun neighborhood(
        nodes: List<GraphNodeInput>,
        edges: List<GraphEdgeInput>,
        seedId: String?,
        width: Float,
        height: Float
    ): GraphPlacement {
        if (nodes.isEmpty()) return GraphPlacement(emptyList(), emptyList())

        val centerX = width.coerceAtLeast(1f) / 2f
        val centerY = height.coerceAtLeast(1f) / 2f
        val center = GraphPoint(centerX, centerY)
        val maxRadius = minOf(centerX, centerY) - EDGE_PADDING
        val maxWeight = nodes.maxOf { it.weight }.coerceAtLeast(0.001f)

        fun radiusOf(node: GraphNodeInput, isSeed: Boolean): Float {
            val normalized = (node.weight / maxWeight).coerceIn(0f, 1f)
            val base = MIN_NODE_RADIUS + normalized * (MAX_NODE_RADIUS - MIN_NODE_RADIUS)
            return if (isSeed) base + SEED_RADIUS_BONUS else base
        }

        val seed = nodes.firstOrNull { it.id == seedId }
        val placed = mutableListOf<GraphPlacedNode>()
        if (seed != null) {
            placed += GraphPlacedNode(
                id = seed.id,
                center = center,
                radius = radiusOf(seed, true),
                isSeed = true,
                ring = 0
            )
        }

        val sectorWidth = 2f * PI.toFloat() / SECTORS.size
        nodes.asSequence()
            .filter { it.id != seed?.id }
            .groupBy { it.distance.coerceIn(1, RING_RATIOS.size) }
            .toSortedMap()
            .forEach { (ring, ringNodes) ->
                val ringRadius = maxRadius * RING_RATIOS[ring - 1]
                ringNodes.groupBy { sectorIndexOf(it.relation) }
                    .toSortedMap()
                    .forEach { (sector, sectorNodes) ->
                        val ordered = sectorNodes.sortedWith(
                            compareByDescending<GraphNodeInput> { it.weight }.thenBy { it.id }
                        )
                        val start = -PI.toFloat() / 2f + sector * sectorWidth
                        ordered.forEachIndexed { index, node ->
                            // 单个节点落在扇区正中，多个节点均分扇区的 70%
                            val fraction = if (ordered.size == 1) {
                                0.5f
                            } else {
                                (index + 0.5f) / ordered.size
                            }
                            val angle = start + sectorWidth * (0.15f + 0.7f * fraction)
                            placed += GraphPlacedNode(
                                id = node.id,
                                center = GraphPoint(
                                    centerX + ringRadius * cos(angle),
                                    centerY + ringRadius * sin(angle)
                                ),
                                radius = radiusOf(node, false),
                                isSeed = false,
                                ring = ring
                            )
                        }
                    }
            }

        val ids = placed.mapTo(HashSet()) { it.id }
        return GraphPlacement(
            nodes = placed,
            edges = edges.filter { it.sourceId in ids && it.targetId in ids },
            center = center,
            compassRadius = maxRadius
        )
    }

    /**
     * 地标层布局：一圈等距地标，最重的一个固定在 12 点方向，顺时针变轻。
     */
    fun anchors(nodes: List<GraphNodeInput>, width: Float, height: Float): GraphPlacement {
        if (nodes.isEmpty()) return GraphPlacement(emptyList(), emptyList())

        val centerX = width.coerceAtLeast(1f) / 2f
        val centerY = height.coerceAtLeast(1f) / 2f
        val orbit = (minOf(centerX, centerY) - ANCHOR_ORBIT_PADDING).coerceAtLeast(24f)
        val ordered = nodes.sortedWith(
            compareByDescending<GraphNodeInput> { it.weight }.thenBy { it.id }
        )
        val maxCount = ordered.maxOf { it.memberCount }.coerceAtLeast(1)
        val step = 2f * PI.toFloat() / ordered.size

        val placed = ordered.mapIndexed { index, node ->
            val angle = -PI.toFloat() / 2f + step * index
            // 成员越多球越大，开根号压一下差距，避免一个大簇吞掉整圈
            val radius = 9f + 9f * sqrt(node.memberCount.toFloat() / maxCount)
            GraphPlacedNode(
                id = node.id,
                center = GraphPoint(centerX + orbit * cos(angle), centerY + orbit * sin(angle)),
                radius = radius,
                isSeed = false,
                ring = 0
            )
        }
        return GraphPlacement(
            nodes = placed,
            edges = emptyList(),
            center = GraphPoint(centerX, centerY),
            compassRadius = orbit
        )
    }

    private fun sectorIndexOf(relation: String): Int {
        val index = SECTORS.indexOf(relation.trim().lowercase())
        return if (index >= 0) index else SECTORS.lastIndex
    }
}
