package com.aveline.ai.mobile.presentation.chat

import com.aveline.ai.mobile.domain.models.ChatAttachment
import com.aveline.ai.mobile.domain.models.ChatAttachmentKind
import com.aveline.ai.mobile.domain.models.Message

/**
 * 从已落库的用户消息重建「真正发给后端的文本」（纯函数，便于单元测试）。
 *
 * 【为什么需要它】
 * 图片/视频消息发给后端时依赖正文里的附件标记：
 * - 图片：`[图片: url]` + caption，后端 `split_chat_image_message` 靠这个标记
 *   把消息还原成标准 OpenAI `image_url` 多模态内容（见 core/image/chat_image_input.py）；
 * - 视频：`[视频: url]` + caption（后端暂无视频理解能力，只认地址）。
 *
 * 但落库时用户气泡的 `text` 只存 caption，地址在 `imageUrl` / `videoUrl` 列里。
 * 发送当时这条标记是现组装的（见 [ImageMessageText.buildAttachment] /
 * [VideoMessageText.build]），**不会持久化**。于是重生成 / 编辑请求时若直接把
 * `message.text`（caption）当正文发出，后端收到的就是纯文字 —— 表现为
 * 「重新生成不把图片带上去，只有文字」。
 *
 * 这里按 messageType 把标记补回来；纯文本消息返回 null，让调用方回退到
 * `userMessage.text`，保持原行为。
 */
object MediaSendText {

    /**
     * 重建发送文本。
     *
     * @return 带上附件标记的完整发送文本；纯文本消息（或地址缺失的异常数据）返回 null。
     */
    fun rebuild(message: Message): String? = when {
        message.attachments.isNotEmpty() -> buildAttachments(message.attachments, message.text)
        message.messageType == "image" && !message.imageUrl.isNullOrBlank() ->
            ImageMessageText.buildAttachment(message.imageUrl, message.text)
        message.messageType == "video" && !message.videoUrl.isNullOrBlank() ->
            VideoMessageText.build(message.videoUrl, message.text)
        else -> null
    }

    fun buildAttachments(attachments: List<ChatAttachment>, caption: String): String {
        val markers = attachments.mapNotNull { attachment ->
            val url = attachment.url.trim()
            if (url.isEmpty()) return@mapNotNull null
            when (attachment.kind) {
                ChatAttachmentKind.IMAGE -> ImageMessageText.buildAttachment(url, "")
                ChatAttachmentKind.DOCUMENT -> "[附件: $url]"
            }
        }
        return (markers + caption.trim().takeIf { it.isNotEmpty() }.orEmpty())
            .filter { it.isNotBlank() }
            .joinToString("\n")
    }
}
