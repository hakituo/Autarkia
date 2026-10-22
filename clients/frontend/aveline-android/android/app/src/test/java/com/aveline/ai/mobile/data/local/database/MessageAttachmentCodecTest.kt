package com.aveline.ai.mobile.data.local.database

import com.aveline.ai.mobile.domain.models.ChatAttachment
import com.aveline.ai.mobile.domain.models.ChatAttachmentKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 附件列 JSON 编解码的回归测试。
 *
 * 这一列是 v6 -> v7 迁移新增的，旧消息该列为 null：
 * 解码必须永远给得出一个列表，坏数据只降级为空，不能让聊天历史整体打不开。
 */
class MessageAttachmentCodecTest {

    private val image = ChatAttachment(
        kind = ChatAttachmentKind.IMAGE,
        url = "/output/image/uploads/a.jpg",
        name = "a.jpg",
        mimeType = "image/jpeg"
    )
    private val document = ChatAttachment(
        kind = ChatAttachmentKind.DOCUMENT,
        url = "/output/uploads/report.pdf",
        name = "report.pdf",
        mimeType = "application/pdf"
    )

    @Test
    fun `无附件时列写空交给 Room`() {
        assertNull(MessageAttachmentCodec.encode(emptyList()))
    }

    @Test
    fun `多附件编解码往返一致`() {
        val attachments = listOf(image, document)

        assertEquals(
            attachments,
            MessageAttachmentCodec.decode(MessageAttachmentCodec.encode(attachments))
        )
    }

    @Test
    fun `旧消息缺列与空串都解码为空列表`() {
        assertEquals(emptyList<ChatAttachment>(), MessageAttachmentCodec.decode(null))
        assertEquals(emptyList<ChatAttachment>(), MessageAttachmentCodec.decode(""))
    }

    @Test
    fun `损坏 JSON 降级为空列表不崩溃`() {
        assertEquals(emptyList<ChatAttachment>(), MessageAttachmentCodec.decode("[{"))
    }

    @Test
    fun `未知字段被忽略以兼容后续版本`() {
        val json = """
            [{"kind":"IMAGE","url":"/output/image/uploads/a.jpg","name":"a.jpg",
              "mimeType":"image/jpeg","futureField":"x"}]
        """.trimIndent()

        assertEquals(listOf(image), MessageAttachmentCodec.decode(json))
    }
}
