package com.aveline.ai.mobile.presentation.chat

import com.aveline.ai.mobile.domain.models.ChatAttachment
import com.aveline.ai.mobile.domain.models.ChatAttachmentKind
import com.aveline.ai.mobile.domain.models.Message
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 重生成 / 编辑时发送文本重建的回归测试。
 *
 * 背景：图片只通过正文里的 `[图片: url]` 附件标记到达后端，落库的 text 只是
 * caption。重生成不重建标记时后端只收到文字，表现为「重新生成不把图片带上去」。
 */
class MediaSendTextTest {

    private fun message(
        text: String,
        messageType: String = "text",
        imageUrl: String? = null,
        videoUrl: String? = null
    ) = Message(
        id = "m1",
        text = text,
        isUser = true,
        timestamp = 1000L,
        messageType = messageType,
        imageUrl = imageUrl,
        videoUrl = videoUrl
    )

    @Test
    fun `图片消息重建出附件标记和文案`() {
        assertEquals(
            "[图片: /output/image/uploads/a.jpg]\n看看这张",
            MediaSendText.rebuild(
                message("看看这张", messageType = "image", imageUrl = "/output/image/uploads/a.jpg")
            )
        )
    }

    @Test
    fun `图片无文案时只发附件标记`() {
        assertEquals(
            "[图片: /output/image/uploads/a.jpg]",
            MediaSendText.rebuild(
                message("", messageType = "image", imageUrl = "/output/image/uploads/a.jpg")
            )
        )
    }

    @Test
    fun `视频消息重建出附件标记和文案`() {
        assertEquals(
            "[视频: /output/video/uploads/a.mp4]\n看这个",
            MediaSendText.rebuild(
                message("看这个", messageType = "video", videoUrl = "/output/video/uploads/a.mp4")
            )
        )
    }

    @Test
    fun `纯文本消息返回 null 交给调用方回退原文`() {
        assertNull(MediaSendText.rebuild(message("普通文本")))
    }

    @Test
    fun `图片地址缺失时不硬造标记`() {
        assertNull(MediaSendText.rebuild(message("看看这张", messageType = "image")))
    }

    @Test
    fun `视频地址缺失时不硬造标记`() {
        assertNull(MediaSendText.rebuild(message("看这个", messageType = "video")))
    }

    @Test
    fun `多图加文档重建出逐个标记和文案`() {
        val attachments = listOf(
            image("/output/image/uploads/a.jpg", "a.jpg"),
            image("/output/image/uploads/b.png", "b.png"),
            document("/output/uploads/report.pdf", "report.pdf")
        )

        assertEquals(
            "[图片: /output/image/uploads/a.jpg]\n" +
                "[图片: /output/image/uploads/b.png]\n" +
                "[附件: /output/uploads/report.pdf]\n" +
                "对比一下",
            MediaSendText.buildAttachments(attachments, "对比一下")
        )
    }

    @Test
    fun `附件消息重建优先于单图地址`() {
        val message = message(
            "对比一下",
            messageType = "attachment",
            imageUrl = "/output/image/uploads/a.jpg"
        ).copy(
            attachments = listOf(image("/output/image/uploads/a.jpg", "a.jpg"))
        )

        assertEquals(
            "[图片: /output/image/uploads/a.jpg]\n对比一下",
            MediaSendText.rebuild(message)
        )
    }

    @Test
    fun `纯附件没有文案时只发标记`() {
        assertEquals(
            "[附件: /output/uploads/notes.md]",
            MediaSendText.buildAttachments(
                listOf(document("/output/uploads/notes.md", "notes.md")),
                "   "
            )
        )
    }

    @Test
    fun `地址缺失的附件不生成标记`() {
        assertEquals(
            "[图片: /output/image/uploads/a.jpg]\n看这个",
            MediaSendText.buildAttachments(
                listOf(
                    image("/output/image/uploads/a.jpg", "a.jpg"),
                    document("   ", "broken.pdf")
                ),
                "看这个"
            )
        )
    }

    private fun image(url: String, name: String) = ChatAttachment(
        kind = ChatAttachmentKind.IMAGE,
        url = url,
        name = name,
        mimeType = "image/jpeg"
    )

    private fun document(url: String, name: String) = ChatAttachment(
        kind = ChatAttachmentKind.DOCUMENT,
        url = url,
        name = name,
        mimeType = "application/pdf"
    )
}
