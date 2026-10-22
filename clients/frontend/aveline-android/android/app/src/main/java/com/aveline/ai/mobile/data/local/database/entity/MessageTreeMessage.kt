package com.aveline.ai.mobile.data.local.database.entity

/**
 * 聊天记录树的精简消息。
 *
 * 树只展示正文、角色、时间和分支关系，不读 audioBase64 / attachmentsJson /
 * imageUrl 这类大字段；[hasMedia] 用 SQL 表达式算好，避免整段历史把媒体正文
 * 全部载入内存。
 */
data class MessageTreeMessage(
    val id: String,
    val text: String,
    val isUser: Boolean,
    val timestamp: Long,
    val messageType: String,
    val sessionId: String?,
    val parentId: String?,
    val variantIndex: Int,
    val isActiveVariant: Boolean,
    val hasMedia: Boolean
)
