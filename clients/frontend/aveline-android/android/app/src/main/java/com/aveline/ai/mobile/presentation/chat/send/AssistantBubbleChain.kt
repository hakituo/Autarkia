package com.aveline.ai.mobile.presentation.chat.send

import android.util.Log
import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.presentation.chat.ChatUiState
import com.aveline.ai.mobile.utils.text.TextSegmenter
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update

/**
 * AI 回复的「气泡链」状态机。
 *
 * 一条回复会被表情包/图片切成多条气泡。它们必须串成**一条链**而不是互为兄弟：
 * 消息树把「同一个父节点 + 同为 AI」的节点当作互为版本，连着发 3 张图会被折叠成
 * 一个槽位，界面只显示第 1 张、右侧多出一个「1/3 切换键」。串成链后每张的兄弟数都是 1。
 *
 * 最终链路形如：
 * ```
 * 正文1 -> 图1 -> 空占位 -> 图2 -> 空占位 -> 图3 -> 正文2
 * ```
 * 空占位渲染成"什么都不显示"，只当链上的连接点。
 */
internal class AssistantBubbleChain(
    private val sessionId: String?,
    private val chatRepository: ChatRepository,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val guard: ChatUiWriteGuard,
    private val generateMessageId: () -> String,
    initialMessageId: String,
    initialParentId: String?,
    initialVariantIndex: Int,
    initialTimestamp: Long
) {
    private companion object {
        const val TAG = "AssistantBubbleChain"
    }

    /** 当前气泡正在累积的正文。 */
    val fullText = StringBuilder()

    /** 当前正在累积正文的气泡 id。 */
    var textMessageId: String = initialMessageId
        private set

    /** 当前气泡挂载的父节点。 */
    var textParentId: String? = initialParentId
        private set

    /** 当前气泡的版本序号（首条承载回复版本，后续分段固定为 0）。 */
    var textVariantIndex: Int = initialVariantIndex
        private set

    /** 当前气泡的起始时间戳。 */
    var textBubbleTimestamp: Long = initialTimestamp
        private set

    /**
     * 把当前正文气泡封口，并为后续文字开一条挂在 [nextParentId] 下的新气泡。
     *
     * 封口 = 把已累积的正文落库（原先只在整轮结束时写一次，有了气泡切分后
     * 每条被封的气泡都得自己写），然后清空缓冲、把"当前气泡"指向新节点。
     * 正文为空时不写库：那条空气泡留在树上当链接（渲染成空气泡，看不见），
     * 保证"回复以表情包开头/结尾"时消息链不断。
     */
    suspend fun sealAndStartNext(nextParentId: String) {
        val sealedText = TextSegmenter.clean(fullText.toString())
        if (sealedText.isNotBlank()) {
            chatRepository.insertMessage(
                Message(
                    id = textMessageId,
                    text = sealedText,
                    isUser = false,
                    timestamp = textBubbleTimestamp,
                    messageType = "text",
                    sessionId = sessionId,
                    parentId = textParentId,
                    variantIndex = textVariantIndex
                )
            ).onFailure { e -> Log.e(TAG, "写入分段正文失败", e) }
            guard.withUiIfActive(sessionId) {
                uiState.update { state ->
                    state.copy(
                        messages = state.messages.map {
                            if (it.id == textMessageId) it.copy(text = sealedText) else it
                        }
                    )
                }
            }
        }
        fullText.clear()

        val nextPlaceholder = Message(
            id = generateMessageId(),
            text = "",
            isUser = false,
            timestamp = System.currentTimeMillis(),
            messageType = "text",
            sessionId = sessionId,
            parentId = nextParentId
        )
        // 上屏必须排在落库**之前**。
        //
        // 反过来（先落库、再上屏）会踩一个偶发闪退：insertMessage 返回后，Room 的
        // Flow 随时可能发射，把 messages 整体替换成"已经包含这条占位"的活跃路径。
        // 若这次发射恰好挤在"落库"和"上屏"之间，紧接着的 append 就把同一条消息
        // 加了第二次，LazyColumn 的 key 重复 →
        // IllegalArgumentException: Key "..." was already used，整个进程闪退。
        // 先上屏、后落库时，随后的 Flow 发射是**整体替换**，天然去重。
        // append 本身再做一层幂等（先按 id 摘掉再追加），双保险。
        guard.withUiIfActive(sessionId) {
            uiState.update { state ->
                state.copy(
                    messages = state.messages.filterNot { it.id == nextPlaceholder.id } +
                        nextPlaceholder
                )
            }
        }
        // 用 insertMessage 而不是 insertMessageVariant：这是正文链上的下一环，
        // 不是同一节点的另一个版本，不能去动兄弟节点的 isActiveVariant
        chatRepository.insertMessage(nextPlaceholder)
            .onFailure { e -> Log.e(TAG, "写入分段占位消息失败", e) }

        textMessageId = nextPlaceholder.id
        textParentId = nextParentId
        textVariantIndex = 0
        textBubbleTimestamp = nextPlaceholder.timestamp
    }
}
