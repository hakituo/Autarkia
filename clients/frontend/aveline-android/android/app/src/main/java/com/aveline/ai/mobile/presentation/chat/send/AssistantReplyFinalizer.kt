package com.aveline.ai.mobile.presentation.chat.send

import android.util.Log
import com.aveline.ai.mobile.domain.models.Emotion
import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.presentation.chat.ChatTtsController
import com.aveline.ai.mobile.presentation.chat.ChatUiState
import com.aveline.ai.mobile.utils.text.TextSegmenter
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update

/**
 * 一轮生成的收尾：空占位清理 / 正文落库 / 完成通知。
 *
 * 抽成独立协作者是因为它有**两个调用方**——正常结束、以及被取消（用户离开页面，
 * 或后端 cancel 了上一轮）。落库口径只能有一处，否则以后改了正常路径必然漏掉取消路径。
 * 注意流式异常分支**不走**这里：异常时这一轮正文不落库，只报错并关掉打字指示器。
 */
internal class AssistantReplyFinalizer(
    private val uiState: MutableStateFlow<ChatUiState>,
    private val chatRepository: ChatRepository,
    private val ttsController: ChatTtsController,
    private val guard: ChatUiWriteGuard,
    private val previewWriter: ConversationPreviewWriter,
    private val replyNotifier: ReplyOutcomeNotifier,
    private val mapEmotion: (String) -> Emotion?
) {
    private companion object {
        const val TAG = "AssistantFinalizer"
    }

    /**
     * @param notify 是否发「回复完成」通知。用户主动停止时传 false：
     *   那是用户自己的动作，不该在他切到别的 App 时弹一条"她回你了"把人叫回来。
     */
    suspend fun finalize(
        sessionId: String?,
        chain: AssistantBubbleChain,
        fullText: String,
        replyText: String,
        hasMedia: Boolean,
        finalEmotion: String?,
        profileFilename: String?,
        notify: Boolean
    ) {
        val finalText = TextSegmenter.clean(fullText)
        val textMessageId = chain.textMessageId
        // 一条内容都没收到时（生成失败、后端返回错误、流静默结束、用户立刻点了停止），
        // 开头插的空占位消息会变成一条空白气泡永久留在会话里：UI 只在
        // showTypingIndicator=true 时把它当 typing 占位渲染，生成一结束 typing 关掉，
        // 它就显形成空气泡，用户看到的就是「AI 回了一条空的」甚至以为卡住了。
        if (finalText.isBlank() && !hasMedia) {
            guard.withUiIfActive(sessionId) { ttsController.stopIfEnabled() }
            chatRepository.deleteMessage(textMessageId).onFailure { e ->
                Log.w(TAG, "清理空白占位消息失败: ${e.message}")
            }
            guard.withUiIfActive(sessionId) {
                uiState.update { state ->
                    state.copy(
                        messages = state.messages.filterNot { it.id == textMessageId },
                        isTyping = false,
                        showTypingIndicator = false
                    )
                }
            }
            return
        }

        val finalMessage = Message(
            id = textMessageId,
            text = finalText,
            isUser = false,
            timestamp = chain.textBubbleTimestamp,
            messageType = "text",
            sessionId = sessionId,
            parentId = chain.textParentId,
            variantIndex = chain.textVariantIndex,
            emotion = finalEmotion
        )

        guard.withUiIfActive(sessionId) {
            uiState.update { state ->
                val updatedMessages = state.messages.map {
                    if (it.id == textMessageId) {
                        it.copy(text = finalText, emotion = finalEmotion)
                    } else {
                        it
                    }
                }
                state.copy(
                    messages = updatedMessages,
                    isTyping = false,
                    showTypingIndicator = false,
                    currentEmotion = finalEmotion?.let { emo -> mapEmotion(emo) }
                        ?: state.currentEmotion
                )
            }
        }

        // 关键：最终落库必须跟随后台生成作用域，绝不能再切回 viewModelScope。
        // 页面即使已经销毁，这一步仍会完成；重新进入聊天后 Room Flow 会直接恢复完整回复。
        val result = chatRepository.insertMessage(finalMessage)
        result.onFailure { e -> Log.e(TAG, "消息版本写库失败", e) }
        if (result.isSuccess && finalMessage.text.isNotBlank()) {
            previewWriter.write(finalMessage, profileFilename)
        }
        // 落库成功后才提醒：用户发完消息切到别的 App，AI 回完这一刻要弹窗把人叫回来。
        // 必须放在这里（而非 withUiIfActive 内）：用户已经离开聊天页时 UI 分支会整段跳过，
        // 而通知恰恰只在离开时才有意义。
        //
        // 通知正文用整轮回复（replyText）而不是最后一条气泡：回复被表情包切成多段后，
        // 末段可能是空气泡（"……[MEME]"结尾），拿它当正文会弹出一条空通知。
        if (result.isSuccess && notify) {
            replyNotifier.notifyIfNeeded(
                message = finalMessage.copy(text = TextSegmenter.clean(replyText)),
                profileFilename = profileFilename
            )
        }
    }
}
