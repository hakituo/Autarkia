package com.aveline.ai.mobile.presentation.chat

import com.aveline.ai.mobile.domain.models.Message
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 会话列表预览构造的回归测试。
 *
 * 预览口径对齐 QQ / 微信消息列表：只展示最后一条看得见的内容，不加"我: "前缀，
 * 也不允许出现整行没有副标题的空白项（等回复占位、表情包空气泡都不能把预览冲成空）。
 */
class ChatPreviewBuilderTest {

    private fun message(
        id: String,
        text: String,
        isUser: Boolean = false,
        messageType: String = "text",
        imageUrl: String? = null,
        videoUrl: String? = null,
        timestamp: Long = 0L
    ) = Message(
        id = id,
        text = text,
        isUser = isUser,
        timestamp = timestamp,
        messageType = messageType,
        imageUrl = imageUrl,
        videoUrl = videoUrl
    )

    @Test
    fun `多附件有文案时预览显示文案`() {
        assertEquals(
            "帮我看看这份报告",
            ChatPreviewBuilder.buildPreviewText(
                text = "帮我看看这份报告",
                messageType = "attachment",
                imageUrl = "/output/image/uploads/a.jpg"
            )
        )
    }

    @Test
    fun `纯附件没有文案时预览显示附件占位`() {
        assertEquals(
            "[附件]",
            ChatPreviewBuilder.buildPreviewText(
                text = "",
                messageType = "attachment"
            )
        )
    }

    @Test
    fun `旧单图消息预览保持图片占位`() {
        assertEquals(
            "[图片]",
            ChatPreviewBuilder.buildPreviewText(
                text = "",
                messageType = "image",
                imageUrl = "/output/image/uploads/a.jpg"
            )
        )
    }

    @Test
    fun `表情包预览显示表情占位`() {
        assertEquals(
            "[表情]",
            ChatPreviewBuilder.buildPreviewText(
                text = "",
                messageType = "image",
                imageUrl = "/output/image/memes/a.gif"
            )
        )
    }

    @Test
    fun `视频消息优先级高于附件类型`() {
        assertEquals(
            "[视频]",
            ChatPreviewBuilder.buildPreviewText(
                text = "看这个",
                messageType = "video",
                videoUrl = "/output/video/uploads/a.mp4"
            )
        )
    }

    @Test
    fun `用户消息不加我前缀`() {
        assertEquals(
            "在吗",
            ChatPreviewBuilder.buildPreviewText(
                text = "在吗",
                messageType = "text"
            )
        )
    }

    @Test
    fun `只剩表情包标签的空气泡显示表情占位`() {
        assertEquals(
            "[表情]",
            ChatPreviewBuilder.buildPreviewText(
                text = "……[MEME]",
                messageType = "text"
            )
        )
    }

    @Test
    fun `真正空的气泡不产生预览`() {
        assertEquals(
            "",
            ChatPreviewBuilder.buildPreviewText(
                text = "",
                messageType = "text"
            )
        )
    }

    @Test
    fun `等回复时回退到用户最后一条可见消息`() {
        val messages = listOf(
            message(id = "1", text = "今天好累", isUser = true, timestamp = 100L),
            message(id = "2", text = "", timestamp = 200L)
        )

        val preview = ChatPreviewBuilder.buildLatestPreview(messages)

        assertEquals("今天好累", preview?.text)
        assertEquals(100L, preview?.message?.timestamp)
    }

    @Test
    fun `表情包回复后面的空气泡不影响预览`() {
        val messages = listOf(
            message(id = "1", text = "哈哈哈", timestamp = 100L),
            message(
                id = "2",
                text = "",
                messageType = "image",
                imageUrl = "/output/image/memes/a.gif",
                timestamp = 200L
            ),
            message(id = "3", text = "", timestamp = 300L)
        )

        val preview = ChatPreviewBuilder.buildLatestPreview(messages)

        assertEquals("[表情]", preview?.text)
        assertEquals(200L, preview?.message?.timestamp)
    }

    @Test
    fun `整段都没有可见内容时返回 null`() {
        val messages = listOf(
            message(id = "1", text = ""),
            message(id = "2", text = "  ")
        )

        assertNull(ChatPreviewBuilder.buildLatestPreview(messages))
    }
}
