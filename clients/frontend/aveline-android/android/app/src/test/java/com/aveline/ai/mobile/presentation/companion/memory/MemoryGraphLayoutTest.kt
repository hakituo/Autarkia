package com.aveline.ai.mobile.presentation.companion.memory

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs

/**
 * 记忆网络布局：确定性、边界、扇区分组与命中测试。
 *
 * 布局是「固定罗盘」而不是力导向，所以这些约束必须锁死：同样的数据每次画出
 * 同一张图，否则用户建立不了空间记忆。
 */
class MemoryGraphLayoutTest {

    private val width = 320f
    private val height = 320f

    private fun node(
        id: String,
        relation: String = "turn",
        distance: Int = 1,
        weight: Float = 1f,
        memberCount: Int = 1
    ) = GraphNodeInput(id, relation, distance, weight, memberCount)

    @Test
    fun seedSitsAtCenterAndNeighborsStayInsideCanvas() {
        val placement = MemoryGraphLayout.neighborhood(
            nodes = listOf(
                node("seed", relation = "self", distance = 0, weight = 3f),
                node("a", distance = 1),
                node("b", distance = 2),
                node("c", distance = 3)
            ),
            edges = emptyList(),
            seedId = "seed",
            width = width,
            height = height
        )

        val seed = placement.nodes.first { it.id == "seed" }
        assertTrue(seed.isSeed)
        assertEquals(width / 2f, seed.center.x, 0.01f)
        assertEquals(height / 2f, seed.center.y, 0.01f)

        placement.nodes.forEach { placed ->
            assertTrue("节点 ${placed.id} 超出画布", placed.center.x >= 0f && placed.center.x <= width)
            assertTrue("节点 ${placed.id} 超出画布", placed.center.y >= 0f && placed.center.y <= height)
        }
    }

    @Test
    fun sameInputProducesSamePlacement() {
        val nodes = listOf(
            node("seed", relation = "self", distance = 0),
            node("b", relation = "turn", distance = 1, weight = 2f),
            node("a", relation = "turn", distance = 1),
            node("c", relation = "topic", distance = 2)
        )

        val first = MemoryGraphLayout.neighborhood(nodes, emptyList(), "seed", width, height)
        val second = MemoryGraphLayout.neighborhood(
            nodes.shuffled(kotlin.random.Random(7)),
            emptyList(),
            "seed",
            width,
            height
        )

        assertEquals(
            first.nodes.associate { it.id to it.center },
            second.nodes.associate { it.id to it.center }
        )
    }

    @Test
    fun nodesWithSameRelationShareASector() {
        val placement = MemoryGraphLayout.neighborhood(
            nodes = listOf(
                node("seed", relation = "self", distance = 0),
                node("turn1", relation = "turn", distance = 1),
                node("turn2", relation = "turn", distance = 1),
                node("topic1", relation = "topic", distance = 1)
            ),
            edges = emptyList(),
            seedId = "seed",
            width = width,
            height = height
        )

        val byId = placement.nodes.associateBy { it.id }
        val turn1 = byId.getValue("turn1").center
        val turn2 = byId.getValue("turn2").center
        val topic1 = byId.getValue("topic1").center
        val centerX = width / 2f
        val centerY = height / 2f

        // 同扇区的两个节点应该落在同一侧；不同扇区不该落在同一位置
        val sameSide = (turn1.x - centerX) * (turn2.x - centerX) +
            (turn1.y - centerY) * (turn2.y - centerY) > 0f
        assertTrue("同关系节点应落在同一侧", sameSide)
        assertTrue(
            "不同关系不应重叠",
            abs(turn1.x - topic1.x) > 0.5f || abs(turn1.y - topic1.y) > 0.5f
        )
    }

    @Test
    fun edgesAreDroppedWhenAnEndpointIsMissing() {
        val placement = MemoryGraphLayout.neighborhood(
            nodes = listOf(
                node("seed", relation = "self", distance = 0),
                node("a", distance = 1)
            ),
            edges = listOf(
                GraphEdgeInput("seed", "a", 0.9f),
                GraphEdgeInput("a", "ghost", 0.9f)
            ),
            seedId = "seed",
            width = width,
            height = height
        )

        assertEquals(1, placement.edges.size)
        assertEquals("seed", placement.edges.first().sourceId)
    }

    @Test
    fun anchorsPutHeaviestAtTopAndKeepEqualOrbit() {
        val placement = MemoryGraphLayout.anchors(
            nodes = listOf(
                node("light", weight = 1f, memberCount = 1),
                node("heavy", weight = 9f, memberCount = 5),
                node("mid", weight = 5f, memberCount = 2)
            ),
            width = width,
            height = height
        )

        val heavy = placement.nodes.first { it.id == "heavy" }
        assertEquals(width / 2f, heavy.center.x, 0.01f)
        assertTrue("最重的地标应在 12 点方向", heavy.center.y < height / 2f)

        val centerX = width / 2f
        val centerY = height / 2f
        val radii = placement.nodes.map {
            val dx = it.center.x - centerX
            val dy = it.center.y - centerY
            kotlin.math.sqrt(dx * dx + dy * dy)
        }
        radii.forEach { assertEquals(radii.first(), it, 0.01f) }
    }

    @Test
    fun hitTestFindsNodeAndIgnoresEmptySpace() {
        val placement = MemoryGraphLayout.neighborhood(
            nodes = listOf(
                node("seed", relation = "self", distance = 0),
                node("a", distance = 1)
            ),
            edges = emptyList(),
            seedId = "seed",
            width = width,
            height = height
        )

        assertNotNull(placement.nodeAt(width / 2f, height / 2f))
        assertEquals("seed", placement.nodeAt(width / 2f, height / 2f))
        assertNull(placement.nodeAt(1f, 1f))
    }
}
