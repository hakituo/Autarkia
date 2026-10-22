package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * 后端 `/api/v1/sessions/{id}/history`（记忆库）与
 * `/api/v1/sessions/{id}/chat-records`（真实聊天记录）共用的历史消息。
 *
 * 注意：后端返回的是 `role` / `content`（记忆层字段），不是发送接口的
 * `isUser` / `text`。之前复用 [MessageDto] 解析，导致拉下来的历史正文全空、
 * 角色全被当成 assistant，聊天树里看不到服务器侧的内容。
 * `thought` 只有 `chat-records` 会返回（心想）。
 */
@Serializable
data class HistoryMessageDto(
    val id: String = "",
    val role: String = "assistant",
    val content: String = "",
    val timestamp: Double = 0.0,
    @SerialName("message_type")
    val messageType: String? = null,
    @SerialName("image_url")
    val imageUrl: String? = null,
    @SerialName("image_base64")
    val imageBase64: String? = null,
    @SerialName("video_url")
    val videoUrl: String? = null,
    @SerialName("audio_base64")
    val audioBase64: String? = null,
    val category: String? = null,
    /** 心想（内心独白），非空即表示这条消息可在聊天记录树里展开查看 */
    val thought: String? = null
)
