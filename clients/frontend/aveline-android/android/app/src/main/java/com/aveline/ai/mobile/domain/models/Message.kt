package com.aveline.ai.mobile.domain.models

import kotlinx.serialization.Serializable

/**
 * Domain model for a chat message.
 * Represents a message in the business logic layer, separate from DTOs and entities.
 */
@Serializable
data class Message(
    val id: String,
    val text: String,
    val isUser: Boolean,
    val timestamp: Long,
    val messageType: String = "text",
    val audioBase64: String? = null,
    val imageUrl: String? = null,
    val imageBase64: String? = null,
    /** 视频/动图地址（后端相对路径或绝对 URL），非空即按视频消息渲染。 */
    val videoUrl: String? = null,
    /** 用户本轮上传的多个图片/文档附件，旧版 imageUrl/videoUrl 字段继续兼容单媒体消息。 */
    val attachments: List<ChatAttachment> = emptyList(),
    val emotion: String? = null,
    val sessionId: String? = null,
    /** 对话树中的父消息；同一父消息下、角色相同的消息互为版本。 */
    val parentId: String? = null,
    val variantIndex: Int = 0,
    val variantCount: Int = 1,
    val isActiveVariant: Boolean = true,
    /**
     * 对方的内心独白（心想）：普通聊天由服务端单独落盘的心想事件归一化而来，
     * 主动消息则从正文前缀「（心想：…）」抠出。非空即可在聊天记录树里展开查看。
     */
    val thought: String? = null
)
