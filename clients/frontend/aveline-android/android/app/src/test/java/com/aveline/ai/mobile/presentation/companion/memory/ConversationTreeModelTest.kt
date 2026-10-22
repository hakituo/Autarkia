package com.aveline.ai.mobile.presentation.companion.memory

import com.aveline.ai.mobile.domain.models.Message
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 聊天记录树模型：倒序渲染 + 心想归一化 + 服务端记录合并。
 */
class ConversationTreeModelTest {

    private fun message(
        id: String,
        text: String,
        isUser: Boolean,
        timestamp: Long,
        parentId: String? = null,
        variantIndex: Int = 0,
        variantCount: Int = 1,
        isActiveVariant: Boolean = true,
        thought: String? = null
    ) = Message(
        id = id,
        text = text,
        isUser = isUser,
        timestamp = timestamp,
        parentId = parentId,
        variantIndex = variantIndex,
        variantCount = variantCount,
        isActiveVariant = isActiveVariant,
        thought = thought
    )

    @Test
    fun linearConversationIsRenderedNewestFirst() {
        val rows = buildConversationTreeRows(
            listOf(
                message("m1", "第一句", true, 1_000L),
                message("m2", "第二句", false, 2_000L, parentId = "m1"),
                message("m3", "第三句", true, 3_000L, parentId = "m2")
            )
        )

        val texts = rows.map { (it as ConversationTreeRow.MessageRow).message.text }
        assertEquals(listOf("第三句", "第二句", "第一句"), texts)
        assertTrue("主世界线不缩进", rows.all { it.depth == 0 })
    }

    @Test
    fun branchRowStaysIndentedAndAboveItsActiveVariant() {
        val rows = buildConversationTreeRows(
            listOf(
                message("m1", "起头", true, 1_000L),
                message("m2a", "版本一", false, 2_000L, "m1", variantCount = 2),
                message("m2b", "版本二", false, 2_100L, "m1", variantIndex = 1, isActiveVariant = false),
                message("m3", "继续", true, 3_000L, parentId = "m2a")
            )
        )

        // 倒序：最新在最上 → 续聊、折叠分支行、激活版本、最早
        assertEquals("m3", (rows[0] as ConversationTreeRow.MessageRow).message.id)
        val branch = rows[1] as ConversationTreeRow.BranchRow
        assertEquals(1, branch.depth)
        assertEquals(1, branch.hiddenCount)
        assertEquals("m2a", (rows[2] as ConversationTreeRow.MessageRow).message.id)
        assertEquals("m1", (rows[3] as ConversationTreeRow.MessageRow).message.id)
    }

    @Test
    fun summaryEntryIsDroppedFromTree() {
        val summary = message("s1", "【历史摘要】前情提要", false, 1_000L)
        assertNull(normalizeForTree(summary))
        assertTrue(mergeConversationMessages(listOf(summary), emptyList()).isEmpty())
    }

    @Test
    fun inlineThoughtIsExtractedFromText() {
        val normalized = normalizeForTree(
            message("p1", "（心想：该提醒她吃药了）\n\n记得吃药哦", false, 1_000L)
        )

        assertEquals("记得吃药哦", normalized?.text)
        assertEquals("该提醒她吃药了", normalized?.thought)
    }

    @Test
    fun remoteThoughtIsBackfilledIntoMatchingLocalMessage() {
        val local = listOf(message("local-1", "记得吃药哦", false, 1_000L))
        val remote = listOf(
            message(
                id = "remote-evt-1",
                text = "记得吃药哦",
                isUser = false,
                timestamp = 1_000L,
                thought = "该提醒她吃药了"
            )
        )

        val merged = mergeConversationMessages(local, remote)

        assertEquals(1, merged.size)
        assertEquals("local-1", merged[0].id)
        assertNull("本地消息的 parentId 不能被改写", merged[0].parentId)
        assertEquals("该提醒她吃药了", merged[0].thought)
    }
}
