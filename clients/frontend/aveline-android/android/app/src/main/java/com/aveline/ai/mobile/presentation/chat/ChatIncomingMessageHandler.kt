package com.aveline.ai.mobile.presentation.chat

import android.util.Log
import com.aveline.ai.mobile.data.remote.api.WebSocketMessage
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.services.media.LocalMediaStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 处理 WebSocket 下发的消息并维护会话列表预览。
 *
 * session 现在按 role 固定，不再能永远通过 `web_{persona}` 字符串反推当前人设；预览归属
 * 由 ChatSessionController 的 session->persona 运行时映射解析，兼容旧 session 的同时避免
 * 同一角色换 persona 后把预览继续写到旧 persona 文件名。
 *
 * 注意这里**不持有**"本页当前 persona"：预览归属必须完全由消息自己的 session 决定，
 * 拿本页 persona 兜底会让并存的多个聊天页互相覆盖副标题（见 [updateLastMessagePreview]）。
 */
class ChatIncomingMessageHandler(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val chatRepository: ChatRepository,
    private val personaLocalMetaRepository: PersonaLocalMetaRepository,
    private val generateMessageId: () -> String,
    private val getSessionId: () -> String?,
    private val resolveProfileFilenameForSession: (String?) -> String?,
    /** 媒体本地仓库：WS 推送的图片/动图收到即落盘，换后端后历史媒体不丢。 */
    private val localMediaStore: LocalMediaStore? = null
) {
    companion object {
        private const val TAG = "ChatIncomingMessageHandler"
    }

    fun handleTextMessage(message: WebSocketMessage.TextMessage) {
        val text = message.text
        if (text.isBlank()) {
            uiState.update { it.copy(isTyping = false, showTypingIndicator = false) }
            return
        }

        val sessionId = getSessionId()
        val messageId = generateMessageId()
        val segments = ChatTextProcessor.smartSegmentText(text)

        if (segments.isEmpty()) {
            uiState.update { it.copy(isTyping = false, showTypingIndicator = false) }
            return
        }

        val newMessages = segments.mapIndexed { index, segment ->
            Message(
                id = if (index == 0) messageId else "${messageId}-${index}",
                text = segment.text,
                isUser = false,
                timestamp = System.currentTimeMillis(),
                messageType = if (segment.isRetraction) "retraction" else "text",
                emotion = message.emotion,
                sessionId = sessionId
            )
        }
        uiState.update { it.copy(messages = it.messages + newMessages) }

        scope.launch(Dispatchers.IO) {
            runCatching {
                newMessages.forEach { msg -> chatRepository.insertMessage(msg) }
            }.onFailure { e ->
                Log.e(TAG, "批量写入消息失败", e)
                uiState.update { it.copy(error = "消息保存失败: ${e.message}") }
            }
        }

        if (text.endsWith("\n\n") || text.isEmpty()) {
            uiState.update { it.copy(isTyping = false, showTypingIndicator = false) }
        }
    }

    fun handleImageResultMessage(message: WebSocketMessage.ImageResult) {
        val imageUrl = message.imageUrl.takeIf { it.isNotBlank() } ?: run {
            Log.w(TAG, "收到空白图片地址，忽略本次 image_result")
            return
        }
        val sessionId = getSessionId()
        val imageMessage = Message(
            id = generateMessageId(),
            text = "",
            isUser = false,
            timestamp = System.currentTimeMillis(),
            messageType = "image",
            imageUrl = imageUrl,
            sessionId = sessionId
        )

        uiState.update { it.copy(messages = it.messages + imageMessage) }
        localMediaStore?.prefetch(imageUrl)
        scope.launch(Dispatchers.IO) {
            runCatching { chatRepository.insertMessage(imageMessage) }
                .onFailure { e ->
                    Log.e(TAG, "写入图片消息失败", e)
                    uiState.update { it.copy(error = "图片消息保存失败: ${e.message}") }
                }
        }
    }

    fun handleVideoResultMessage(message: WebSocketMessage.VideoResult) {
        val videoUrl = message.videoUrl.takeIf { it.isNotBlank() } ?: run {
            Log.w(TAG, "收到空白视频地址，忽略本次 video_result")
            return
        }
        val sessionId = getSessionId()
        val videoMessage = Message(
            id = generateMessageId(),
            text = "",
            isUser = false,
            timestamp = System.currentTimeMillis(),
            messageType = "video",
            videoUrl = videoUrl,
            sessionId = sessionId
        )
        uiState.update { it.copy(messages = it.messages + videoMessage) }
        localMediaStore?.prefetch(videoUrl)

        scope.launch(Dispatchers.IO) {
            runCatching { chatRepository.insertMessage(videoMessage) }
                .onFailure { e ->
                    Log.e(TAG, "写入视频消息失败", e)
                    uiState.update { it.copy(error = "视频消息保存失败: ${e.message}") }
                }
        }
    }

    /**
     * 把当前会话最后一条消息写入 PersonaLocalMeta。
     *
     * 归属**只认消息自身的 sessionId** 解析出的 persona。这一条不能有"猜"的兜底：
     * `ChatSessionObserver` 订阅的是全局当前会话，所有存活的聊天页都会收到同一份消息；
     * 一旦解析失败就回落到本页 persona，每个页面都会把别人的消息写成自己的预览 ——
     * 现象正是「Ling / Aveline / Ye 三行副标题一模一样」。
     *
     * 解析不到就跳过：少一行副标题只是不好看，写错是把别人的私聊内容挂到另一个角色名下。
     * 用户消息与 AI 回复的预览另有 `ConversationPreviewWriter` 这条权威路径，
     * 这里的 Room 回流只作为补充，不承担"必须写进去"的责任。
     */
    fun updateLastMessagePreview(messages: List<Message>) {
        scope.launch(Dispatchers.IO) {
            if (messages.isEmpty()) {
                val filename = resolveProfileFilenameForSession(getSessionId()) ?: return@launch
                personaLocalMetaRepository.updateLastMessage(
                    profileFilename = filename,
                    preview = null,
                    timestamp = null
                )
                return@launch
            }

            // 不能直接取 messages.last()：等 AI 回复时最后一条是空文本占位，
            // 表情包回复后面还挂着空气泡当链接点，取最后一条会让列表副标题整行空白。
            // 这里回退到"最后一条看得见的消息"（QQ/微信列表口径）。
            val preview = ChatPreviewBuilder.buildLatestPreview(messages) ?: return@launch
            val source = preview.message
            val filename = resolveProfileFilenameForSession(source.sessionId) ?: return@launch
            personaLocalMetaRepository.updateLastMessage(
                profileFilename = filename,
                preview = preview.text,
                timestamp = source.timestamp
            )
        }
    }
}
