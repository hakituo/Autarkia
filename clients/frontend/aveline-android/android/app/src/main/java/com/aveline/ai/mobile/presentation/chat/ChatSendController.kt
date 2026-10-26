package com.aveline.ai.mobile.presentation.chat

import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.domain.models.ChatAttachment
import com.aveline.ai.mobile.domain.models.Emotion
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.presentation.chat.send.AssistantReplyStreamer
import com.aveline.ai.mobile.presentation.chat.send.ChatUiWriteGuard
import com.aveline.ai.mobile.presentation.chat.send.ConversationPreviewWriter
import com.aveline.ai.mobile.presentation.chat.send.ReplyOutcomeNotifier
import com.aveline.ai.mobile.presentation.chat.send.SendPreflight
import com.aveline.ai.mobile.presentation.chat.send.SendRuntime
import com.aveline.ai.mobile.services.foreground.RoleReplyNotifier
import com.aveline.ai.mobile.services.media.LocalMediaStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 负责"发消息"的入口（薄壳门面）。
 *
 * 一条发送请求被拆成三段，各自有独立文件：
 * - [SendPreflight]：清输入框 / persona 切换 / 历史窗口 / 用户消息落库 / 取消兜底
 * - [AssistantReplyStreamer]：HTTP SSE 流式生成 + 气泡链 + 落库 + 完成通知
 * - [ConversationPreviewWriter]：会话列表副标题的**唯一**写入点
 *
 * 本类只做编排：决定这一轮归哪个会话、什么时候登记/取消、以及把三段串起来。
 * 拆开的直接动因是它曾膨胀到 1100 行，而"预览串台"的根因恰好藏在
 * `persistConversationPreview` 的三层归属兜底里 —— 在一大坨流式状态机旁边
 * 读那一小段归属逻辑，几乎不可能看出它在猜角色。
 *
 * 生成事务不能绑定聊天页 ViewModel 生命周期：用户发完消息返回会话列表时
 * ChatViewModel 会被销毁。因此发送准备 + 真正生成 + 持久化统一跑在
 * [SendRuntime] 的进程级作用域；UI/TTS 更新仍受 [scope] 生命周期约束。
 */
class ChatSendController(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val chatRepository: ChatRepository,
    private val personaLocalMetaRepository: PersonaLocalMetaRepository,
    private val sessionController: ChatSessionController,
    private val ttsController: ChatTtsController,
    private val flushManager: ChatFlushManager,
    private val mapEmotion: (String) -> Emotion?,
    private val resolveRoleModelRoute: () -> String? = { null },
    /**
     * 后台回复通知发布器。
     *
     * 用户主动发消息走 HTTP SSE，回复完成时 WebSocket 侧被抑制（见 ChatFlushManager），
     * 因此 SSE 收尾必须自己弹通知，否则「切出去等回复」永远收不到提示。
     * 可空 + 默认值：单测直接构造时不传。
     */
    private val replyNotifier: RoleReplyNotifier? = null,
    /** 媒体本地仓库：SSE 收到表情包/图片立即落盘。可空 + 默认值：单测直接构造时不传。 */
    private val localMediaStore: LocalMediaStore? = null
) {
    companion object {
        /** HTTP SSE 是否在跑（进程级，供新页面继承 WS 抑制状态）。 */
        val backgroundHttpStreamingActive: StateFlow<Boolean>
            get() = SendRuntime.backgroundHttpStreamingActive
    }

    private val guard = ChatUiWriteGuard(scope, uiState, sessionController)

    private val previewWriter = ConversationPreviewWriter(
        personaLocalMetaRepository = personaLocalMetaRepository,
        sessionController = sessionController
    )

    private val outcomeNotifier = ReplyOutcomeNotifier(
        personaLocalMetaRepository = personaLocalMetaRepository,
        replyNotifier = replyNotifier
    )

    private val preflight = SendPreflight(
        uiState = uiState,
        chatRepository = chatRepository,
        sessionController = sessionController,
        guard = guard,
        writePreview = { message, profileFilename -> previewWriter.write(message, profileFilename) }
    )

    private val streamer = AssistantReplyStreamer(
        uiState = uiState,
        chatRepository = chatRepository,
        ttsController = ttsController,
        flushManager = flushManager,
        guard = guard,
        previewWriter = previewWriter,
        replyNotifier = outcomeNotifier,
        mapEmotion = mapEmotion,
        resolveRoleModelRoute = resolveRoleModelRoute,
        localMediaStore = localMediaStore
    )

    fun sendMessage(
        text: String,
        model: String = "default",
        imageUrl: String? = null,
        videoUrl: String? = null,
        displayText: String? = null,
        attachments: List<ChatAttachment> = emptyList()
    ) {
        if (text.isBlank()) return
        val entrySessionId = sessionController.conversationSessionId
        // 预检去重：同一次点击只允许一轮预检进入，避免 N 个 POST 几乎同时发出。
        val sendKey = preflight.tryAcquire(entrySessionId) ?: return

        SendRuntime.launch(
            sessionId = entrySessionId,
            onCancelled = { selfJob -> cancelRescue(entrySessionId, selfJob) }
        ) {
            // 兜底原文：图片/视频路径传的是 caption，文本路径就是正文本身。
            val fallbackText = displayText ?: text
            // 用户气泡是否已经落库。决定取消时要不要把原文还回输入框：
            // 已经发出去的消息不该再在输入框里留一份（用户会以为根本没发出去）。
            var userMessageInserted = false
            try {
                val prepared = (try {
                    preflight.prepare(
                        entrySessionId = entrySessionId,
                        pendingText = fallbackText,
                        imageUrl = imageUrl,
                        videoUrl = videoUrl,
                        attachments = attachments,
                        generateMessageId = SendRuntime::generateMessageId
                    )
                } finally {
                    // 无论成功、失败还是抛异常都要放开去重锁，否则这个会话会永久发不出消息。
                    // 生成过程不占锁：生成期间用户主动再发一条仍然允许（后端会 cancel 上一条）。
                    preflight.release(sendKey)
                }) ?: return@launch

                userMessageInserted = true
                streamer.start(
                    userMessage = prepared.userMessage,
                    prefixHistory = prepared.prefixHistory,
                    model = model,
                    assistantVariantIndex = 0,
                    profileFilename = prepared.profileFilename,
                    sendText = text
                )
            } catch (e: CancellationException) {
                // 预检阶段就被取消：用户离开页面，或同一会话起了新一轮。
                // 已经落库的消息不撤回原文，只把输入框里没发出去的字还回去。
                val selfJob = currentCoroutineContext()[Job]
                withContext(NonCancellable) {
                    preflight.rescueCancelledSend(
                        sessionId = entrySessionId,
                        selfJob = selfJob,
                        originalText = fallbackText,
                        restoreText = !userMessageInserted
                    )
                }
                throw e
            }
        }
    }

    /** 编辑某个用户请求会创建同级新版本，旧请求及其后续分支不会删除。 */
    fun editUserMessage(messageId: String, newText: String, model: String = "default") {
        if (newText.isBlank()) return
        val sessionId = sessionController.conversationSessionId
        SendRuntime.launch(
            sessionId = sessionId,
            onCancelled = { selfJob -> cancelRescue(sessionId, selfJob) }
        ) {
            val currentPath = sessionController.conversationSessionId?.let {
                chatRepository.observeMessages(it).first()
            } ?: return@launch
            val originalIndex = currentPath.indexOfFirst { it.id == messageId && it.isUser }
            if (originalIndex < 0) return@launch
            val original = currentPath[originalIndex]
            val prefixHistory = currentPath.take(originalIndex)
            val edited = original.copy(
                id = SendRuntime.generateMessageId(),
                text = newText.trim(),
                timestamp = System.currentTimeMillis(),
                variantIndex = original.variantCount,
                variantCount = original.variantCount + 1,
                isActiveVariant = true
            )
            chatRepository.insertMessageVariant(edited)
            streamer.start(
                userMessage = edited,
                prefixHistory = prefixHistory,
                model = model,
                assistantVariantIndex = 0,
                profileFilename = sessionController.conversationProfileFilename
                    ?: sessionController.profileFilenameForSessionOwned(edited.sessionId),
                userVariantOfId = original.id,
                // 编辑图片/视频请求时把附件标记补回发送文本：落库的 text 只是 caption，
                // 不发标记后端就只收到文字，图不会上去（见 MediaSendText）。
                sendText = MediaSendText.rebuild(edited)
            )
        }
    }

    /** 对指定 AI 回复重新生成，生成结果作为同一用户请求下的新回复版本。 */
    fun regenerateMessage(messageId: String, model: String = "default") {
        val sessionId = sessionController.conversationSessionId
        SendRuntime.launch(
            sessionId = sessionId,
            onCancelled = { selfJob -> cancelRescue(sessionId, selfJob) }
        ) {
            val currentPath = sessionController.conversationSessionId?.let {
                chatRepository.observeMessages(it).first()
            } ?: return@launch
            val aiIndex = currentPath.indexOfFirst { it.id == messageId && !it.isUser }
            if (aiIndex < 1) return@launch
            // 一条回复可能被表情包/断句切成多条气泡（正文1 -> 图 -> 正文2）。
            // 点其中任意一条都应该重新生成**整轮**，所以往回找到本轮的第一条 AI 气泡 ——
            // 它才是挂在用户消息下、承载版本号的那个节点；直接拿被点的那条当"原回复"
            // 会在第二条气泡上退化成"前一条是图，不是用户消息"从而静默失败。
            var turnStart = aiIndex
            while (turnStart - 1 >= 1 && !currentPath[turnStart - 1].isUser) {
                turnStart--
            }
            val userMessage = currentPath[turnStart - 1]
            if (!userMessage.isUser) return@launch
            val original = currentPath[turnStart]
            streamer.start(
                userMessage = userMessage,
                prefixHistory = currentPath.take(turnStart - 1),
                model = model,
                assistantVariantIndex = original.variantCount,
                profileFilename = sessionController.conversationProfileFilename
                    ?: sessionController.profileFilenameForSessionOwned(userMessage.sessionId),
                assistantVariantOfId = original.id,
                // 图片/视频请求重新生成时把附件标记补回发送文本：落库的 text 只是
                // caption，不发标记后端就只收到文字，图不会上去（见 MediaSendText）。
                sendText = MediaSendText.rebuild(userMessage)
            )
        }
    }

    fun selectVariant(messageId: String, offset: Int) {
        val message = uiState.value.messages.firstOrNull { it.id == messageId } ?: return
        val target = message.variantIndex + offset
        if (target !in 0 until message.variantCount) return
        scope.launch {
            chatRepository.selectSiblingVariant(message, target).onFailure { e ->
                uiState.update { it.copy(error = "切换消息版本失败: ${e.message}") }
            }
        }
    }

    /**
     * 取消发生后的兜底：只关打字指示器，不动输入框（调用方可能已经自行处理原文）。
     *
     * 必须 NonCancellable：此刻协程已是取消态，收尾里的每个挂起点都会立刻再抛
     * CancellationException，收尾会半途而废。
     */
    private suspend fun cancelRescue(sessionId: String?, selfJob: Job?) {
        withContext(NonCancellable) {
            preflight.rescueCancelledSend(
                sessionId = sessionId,
                selfJob = selfJob,
                originalText = null,
                restoreText = false
            )
        }
    }
}
