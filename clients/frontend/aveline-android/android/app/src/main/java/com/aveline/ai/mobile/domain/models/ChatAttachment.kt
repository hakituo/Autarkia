package com.aveline.ai.mobile.domain.models

import kotlinx.serialization.Serializable

@Serializable
enum class ChatAttachmentKind {
    IMAGE,
    DOCUMENT
}

@Serializable
data class ChatAttachment(
    val kind: ChatAttachmentKind,
    val url: String,
    val name: String,
    val mimeType: String = "application/octet-stream"
)
