package com.aveline.ai.mobile.data.local.database

import com.aveline.ai.mobile.domain.models.ChatAttachment
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

internal object MessageAttachmentCodec {
    private val json = Json { ignoreUnknownKeys = true }
    private val serializer = ListSerializer(ChatAttachment.serializer())

    fun encode(attachments: List<ChatAttachment>): String? =
        attachments.takeIf { it.isNotEmpty() }?.let { json.encodeToString(serializer, it) }

    fun decode(value: String?): List<ChatAttachment> {
        if (value.isNullOrBlank()) return emptyList()
        return runCatching { json.decodeFromString(serializer, value) }.getOrDefault(emptyList())
    }
}
