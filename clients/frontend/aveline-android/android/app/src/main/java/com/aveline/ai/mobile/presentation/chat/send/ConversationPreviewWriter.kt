package com.aveline.ai.mobile.presentation.chat.send

import android.util.Log
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.presentation.chat.ChatPreviewBuilder
import com.aveline.ai.mobile.presentation.chat.ChatSessionController

/**
 * 会话列表副标题的**唯一写入点**。
 *
 * 这一层存在的理由是一个真实缺陷：预览归属以前分散在三处，各自带一层"解析不到就
 * 猜一个 persona"的兜底 ——
 *
 * - `ChatIncomingMessageHandler` 最后回落到 `getProfileFilename()`（本页正在聊的 persona）
 * - `ChatSendController` 用 `profileFilenameForPreview()`（当前 role 名下任意一个人设）
 * - `ConversationListViewModel` 用 `web_{filename}` 硬拼
 *
 * 只要某一层猜错，**别人的消息就会被写成自己的预览**。用户看到的现象正是：
 * Ling / Aveline / Ye 三行副标题完全一样、时间都显示"刚刚"，点进去内容却完全不同。
 *
 * 现在的口径只有一条：**认不出归属就不写**。列表副标题缺失只是少一行字，
 * 写错则是把别人的私聊内容显示在另一个人名下 —— 后者的代价高得多。
 */
internal class ConversationPreviewWriter(
    private val personaLocalMetaRepository: PersonaLocalMetaRepository,
    private val sessionController: ChatSessionController
) {
    private companion object {
        const val TAG = "ConversationPreview"
    }

    /**
     * 写入一条消息的列表预览。
     *
     * @param message 已落库的消息（时间戳以它自己为准，不用"当前时间"）
     * @param frozenProfileFilename 发送/生成开始时冻结的本页 persona。
     *   这是最可靠的归属：它由用户真正打开的那个角色决定，不随后端全局
     *   active persona 漂移。为空时才回落到会话归属查询。
     */
    suspend fun write(message: Message, frozenProfileFilename: String? = null) {
        val filename = resolveOwner(message.sessionId, frozenProfileFilename)
        if (filename.isNullOrBlank()) {
            Log.w(
                TAG,
                "预览归属未知，跳过写入: session=${message.sessionId} " +
                    "frozen=${frozenProfileFilename ?: "(null)"}"
            )
            return
        }
        val preview = ChatPreviewBuilder.buildPreviewText(
            text = message.text,
            messageType = message.messageType,
            imageUrl = message.imageUrl,
            videoUrl = message.videoUrl
        )
        // 空文本（AI 占位、媒体链连接点）不能覆盖已有副标题，
        // 否则会话列表会出现一行没有副标题的空白项。
        if (preview.isBlank()) return

        runCatching {
            personaLocalMetaRepository.updateLastMessage(
                profileFilename = filename,
                preview = preview,
                timestamp = message.timestamp
            )
        }.onFailure { e ->
            Log.w(TAG, "更新会话预览失败: ${e.message}")
        }
    }

    /**
     * 解析一条会话归属的 persona。
     *
     * 顺序固定，且每一步都不"猜"：
     * 1. 冻结的本页 persona（发送时确定，权威）
     * 2. 该 session 在**本角色**范围内的登记归属
     * 3. 认不出 → null
     */
    fun resolveOwner(sessionId: String?, frozenProfileFilename: String?): String? {
        frozenProfileFilename?.takeIf { it.isNotBlank() }?.let { return it }
        return sessionController.profileFilenameForSessionOwned(sessionId)
    }
}
