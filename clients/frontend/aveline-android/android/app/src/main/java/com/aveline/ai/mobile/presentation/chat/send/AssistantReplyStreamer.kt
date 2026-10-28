package com.aveline.ai.mobile.presentation.chat.send

import android.util.Log
import com.aveline.ai.mobile.data.remote.api.StreamEvent
import com.aveline.ai.mobile.data.remote.api.errorFromThrowable
import com.aveline.ai.mobile.domain.models.Emotion
import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.domain.repository.ChatBranchContext
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.presentation.chat.ChatFlushManager
import com.aveline.ai.mobile.presentation.chat.ChatTtsController
import com.aveline.ai.mobile.presentation.chat.ChatUiState
import com.aveline.ai.mobile.services.media.LocalMediaStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.withContext

/**
 * HTTP SSE 流式回复的生成与落地。
 *
 * 从发送控制器里独立出来的原因：这一段有 8 个可变中间态（正文缓冲、当前气泡、
 * 是否产出过媒体、是否收到 Done…），和"点发送后怎么预检"是完全不同的心智负担。
 * 混在一个文件里时，任何一处改动都要先把另一段的状态机在脑子里跑一遍。
 *
 * 事务边界：由 [SendRuntime] 的进程级作用域承载，页面销毁不打断生成；
 * UI/TTS 写入统一过 [ChatUiWriteGuard]，页面没了就只落库、不碰界面。
 */
internal class AssistantReplyStreamer(
    private val uiState: MutableStateFlow<ChatUiState>,
    private val chatRepository: ChatRepository,
    private val ttsController: ChatTtsController,
    private val flushManager: ChatFlushManager,
    private val guard: ChatUiWriteGuard,
    private val previewWriter: ConversationPreviewWriter,
    private val replyNotifier: ReplyOutcomeNotifier,
    private val mapEmotion: (String) -> Emotion?,
    private val resolveRoleModelRoute: () -> String? = { null },
    /** 当前角色这一轮要不要开思考模式；null = 跟随后端配置。 */
    private val resolveRoleThinking: () -> Boolean? = { null },
    /** 媒体本地仓库：SSE 推送的图片/表情包收到即落盘。可空 + 默认值：单测不传。 */
    private val localMediaStore: LocalMediaStore? = null
) {
    private companion object {
        const val TAG = "AssistantReplyStreamer"
    }

    private val finalizer = AssistantReplyFinalizer(
        uiState = uiState,
        chatRepository = chatRepository,
        ttsController = ttsController,
        guard = guard,
        previewWriter = previewWriter,
        replyNotifier = replyNotifier,
        mapEmotion = mapEmotion
    )

    /**
     * 冻结本次请求的模型和消息 ID，后续不再读取可变的当前 persona/model，
     * 避免用户退出后切到其它角色导致串路由。
     *
     * 调用方已位于进程级后台作用域。
     */
    suspend fun start(
        userMessage: Message,
        prefixHistory: List<Message>,
        model: String,
        assistantVariantIndex: Int,
        profileFilename: String?,
        sendText: String? = null,
        userVariantOfId: String? = null,
        assistantVariantOfId: String? = null
    ) {
        val requestModel = resolveRoleModelRoute()?.takeIf { it.isNotBlank() } ?: model
        // 思考开关同样在这一刻冻结：生成中途切角色/改开关不该影响已经在飞的这一轮
        run(
            userMessage = userMessage,
            prefixHistory = prefixHistory,
            requestModel = requestModel,
            thinking = resolveRoleThinking(),
            profileFilename = profileFilename,
            assistantVariantIndex = assistantVariantIndex,
            aiMessageId = SendRuntime.generateMessageId(),
            sendText = sendText,
            userVariantOfId = userVariantOfId,
            assistantVariantOfId = assistantVariantOfId
        )
    }

    private suspend fun run(
        userMessage: Message,
        prefixHistory: List<Message>,
        requestModel: String,
        thinking: Boolean?,
        profileFilename: String?,
        assistantVariantIndex: Int,
        aiMessageId: String,
        sendText: String? = null,
        userVariantOfId: String? = null,
        assistantVariantOfId: String? = null
    ) {
        val sessionId = userMessage.sessionId
        val aiMessageStart = System.currentTimeMillis()
        val aiPlaceholder = Message(
            id = aiMessageId,
            text = "",
            isUser = false,
            timestamp = aiMessageStart,
            messageType = "text",
            sessionId = sessionId,
            parentId = userMessage.id,
            variantIndex = assistantVariantIndex,
            variantCount = (assistantVariantIndex + 1).coerceAtLeast(1)
        )
        // 与用户气泡同理：占位消息先上屏，「对方正在输入」立刻出现，
        // 后面的 SSE 首字节等待才不会被误读成"卡住了"。
        guard.withUiIfActive(sessionId) {
            uiState.update {
                it.copy(
                    messages = it.messages + aiPlaceholder,
                    isTyping = true,
                    showTypingIndicator = true,
                    inputText = "",
                    error = null
                )
            }
            ttsController.startStreamingIfEnabled(aiMessageId)
        }
        chatRepository.insertMessageVariant(aiPlaceholder)

        // 本轮生成的任务登记/摘除由外层 SendRuntime.launch 统一负责：它从预检之前
        // 就开始覆盖，而这里只能覆盖"占位气泡上屏之后"的一段，登记晚一步就会出现
        // "按钮已经能按、表里却还没得可停"的空窗。
        val chain = AssistantBubbleChain(
            sessionId = sessionId,
            chatRepository = chatRepository,
            uiState = uiState,
            guard = guard,
            generateMessageId = SendRuntime::generateMessageId,
            initialMessageId = aiMessageId,
            initialParentId = userMessage.id,
            initialVariantIndex = assistantVariantIndex,
            initialTimestamp = aiMessageStart
        )
        // 本轮回复的全部正文（跨多条气泡）。只用于后台通知的正文，不影响落库结构。
        val replyText = StringBuilder()
        var finalEmotion: String? = null
        // 是否产出过图片/视频：这类回复正文可以是空的（AI 只丢一张表情包），
        // 此时空占位消息要保留 —— 图片消息的 parentId 挂在它下面，删了就成孤儿。
        var hasMedia = false

        // 用计数器派生出的值同步 WS 抑制，而不是写死 true：同一会话上一轮可能还没收完。
        flushManager.setHttpStreamingActive(SendRuntime.markHttpStreamStarted())
        try {
            // 图片消息的用户气泡 text 存的是「用户文案（caption）」，真正要发给后端的是
            // 识别结果文本（含 [图像识别结果：...] + caption）。sendText 只在图片发送路径
            // 显式传入，其余路径回退到 userMessage.text 保持原行为。
            val effectiveSendText = sendText ?: userMessage.text
            chatRepository.sendMessageStreaming(
                effectiveSendText,
                sessionId,
                requestModel,
                profileFilename,
                prefixHistory,
                ChatBranchContext(
                    userMessage = userMessage,
                    assistantMessage = aiPlaceholder,
                    userVariantOfId = userVariantOfId,
                    assistantVariantOfId = assistantVariantOfId
                ),
                thinking = thinking
            ).collect { event ->
                when (event) {
                    is StreamEvent.Chunk -> {
                        chain.fullText.append(event.content)
                        replyText.append(event.content)
                        guard.withUiIfActive(sessionId) {
                            ttsController.appendStreamingChunk(event.content)
                            uiState.update { state ->
                                val updatedMessages = state.messages.map {
                                    if (it.id == chain.textMessageId) {
                                        it.copy(text = chain.fullText.toString())
                                    } else {
                                        it
                                    }
                                }
                                state.copy(messages = updatedMessages)
                            }
                        }
                    }
                    is StreamEvent.Done -> {
                        finalEmotion = event.emotion
                        guard.withUiIfActive(sessionId) {
                            ttsController.finishStreamingIfEnabled()
                        }
                    }
                    is StreamEvent.Error -> {
                        guard.withUiIfActive(sessionId) {
                            ttsController.stopIfEnabled()
                            uiState.update {
                                it.copy(
                                    // describe() 会带上后端给的错误码/详情，不再只剩一句笼统文案
                                    error = "生成失败: ${event.describe()}",
                                    isTyping = false,
                                    showTypingIndicator = false
                                )
                            }
                        }
                    }
                    is StreamEvent.Reset -> {
                        // 只清当前这条气泡：AI 开始调用工具，正在生成的临时消息作废。
                        // 已经被表情包"封口"的前几条气泡保持不动（正文确实已经发出去了）。
                        chain.fullText.clear()
                        guard.withUiIfActive(sessionId) {
                            ttsController.finishStreamingIfEnabled()
                            uiState.update { state ->
                                val updatedMessages = state.messages.map {
                                    if (it.id == chain.textMessageId) it.copy(text = "") else it
                                }
                                state.copy(
                                    messages = updatedMessages,
                                    isTyping = true,
                                    showTypingIndicator = true
                                )
                            }
                        }
                    }
                    is StreamEvent.ImageResult -> {
                        hasMedia = true
                        // 收到即落盘：用户滚到这条消息前文件已在本地，冷启动直接读文件
                        localMediaStore?.prefetch(event.imageUrl)
                        // 图挂在"当前正文气泡"后面；封口后会在图下面新开一条正文气泡，
                        // 下一张图再挂到那条新气泡下，连发多张时自然串成一条链。
                        val imageMessage = Message(
                            id = SendRuntime.generateMessageId(),
                            text = "",
                            isUser = false,
                            timestamp = System.currentTimeMillis(),
                            messageType = "image",
                            imageUrl = event.imageUrl,
                            sessionId = sessionId,
                            parentId = chain.textMessageId
                        )
                        guard.withUiIfActive(sessionId) {
                            uiState.update { state ->
                                state.copy(messages = state.messages + imageMessage)
                            }
                        }
                        val result = chatRepository.insertMessage(imageMessage)
                        result.onFailure { e -> Log.e(TAG, "写入图片消息失败", e) }
                        if (result.isSuccess) {
                            previewWriter.write(imageMessage, profileFilename)
                        }
                        // 再把刚发完的那句话封口，后续文字开一条挂在图下面的新气泡：
                        // 最终链路是 正文1 -> 图 -> 正文2 -> 图 -> 正文3
                        chain.sealAndStartNext(imageMessage.id)
                    }
                    is StreamEvent.VideoResult -> {
                        hasMedia = true
                        // 收到即落盘：与图片同理，滚动到这条消息前文件已在本地
                        localMediaStore?.prefetch(event.videoUrl)
                        // 与图片同理：视频也接在"当前正文气泡"后面，由封口逻辑串成链
                        val videoMessage = Message(
                            id = SendRuntime.generateMessageId(),
                            text = "",
                            isUser = false,
                            timestamp = System.currentTimeMillis(),
                            messageType = "video",
                            videoUrl = event.videoUrl,
                            sessionId = sessionId,
                            parentId = chain.textMessageId
                        )
                        guard.withUiIfActive(sessionId) {
                            uiState.update { state ->
                                state.copy(messages = state.messages + videoMessage)
                            }
                        }
                        val result = chatRepository.insertMessage(videoMessage)
                        result.onFailure { e -> Log.e(TAG, "写入视频消息失败", e) }
                        if (result.isSuccess) {
                            previewWriter.write(videoMessage, profileFilename)
                        }
                        chain.sealAndStartNext(videoMessage.id)
                    }
                }
            }
        } catch (e: CancellationException) {
            // 取消信号必须原样上抛（吞掉会让上层误以为这一轮"正常跑完了"），
            // 但**收尾不能跟着一起跳过** —— 直接上抛的话 isTyping 会永远停在 true、
            // 已经流出来的正文也不会落库。所以先在 NonCancellable 里走一遍收尾
            // （只是不发"回复完成"通知），再上抛。
            withContext(NonCancellable) {
                finalizer.finalize(
                    sessionId = sessionId,
                    chain = chain,
                    fullText = chain.fullText.toString(),
                    replyText = replyText.toString(),
                    hasMedia = hasMedia,
                    finalEmotion = finalEmotion,
                    profileFilename = profileFilename,
                    notify = false
                )
            }
            throw e
        } catch (e: Exception) {
            // 兜底：流式过程中任何未预期异常都只让"这一轮"失败，不再冒泡到线程默认
            // 异常处理器把整个进程带走 —— 那正是"角色发图时偶尔闪退"当初的表现形式。
            Log.e(TAG, "生成回复过程中发生未预期异常", e)
            guard.withUiIfActive(sessionId) {
                uiState.update {
                    it.copy(
                        // 带上异常类型与原始 message，别只给用户一句无法定位的 "内部错误"
                        error = errorFromThrowable(e, "生成失败").describe(),
                        isTyping = false,
                        showTypingIndicator = false
                    )
                }
            }
        } finally {
            // 生成任务的登记/摘除由 SendRuntime.launch 负责（见那里对登记时机的说明），
            // 这里只做流式通道状态收尾。
            // 先摘计数器再同步抑制开关：本轮可能是"旧轮"，此时新一轮还在跑，
            // 计数不会归零，返回值仍是 true，WS 抑制不会被提前放开。
            flushManager.setHttpStreamingActive(SendRuntime.markHttpStreamFinished())
        }

        // 正常结束：收尾统一走 finalizer（与被取消收尾共用同一套落库口径）。
        finalizer.finalize(
            sessionId = sessionId,
            chain = chain,
            fullText = chain.fullText.toString(),
            replyText = replyText.toString(),
            hasMedia = hasMedia,
            finalEmotion = finalEmotion,
            profileFilename = profileFilename,
            notify = true
        )
    }
}
