package com.aveline.ai.mobile.presentation.chat.send

import android.util.Log
import com.aveline.ai.mobile.domain.models.ChatAttachment
import com.aveline.ai.mobile.domain.models.ChatAttachmentKind
import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.presentation.chat.ChatSessionController
import com.aveline.ai.mobile.presentation.chat.ChatUiState
import java.util.concurrent.ConcurrentHashMap
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update

/**
 * 发送预检：清空输入框 → persona 切换 → 组装正文窗口 → 用户消息落库。
 *
 * 这一段的每一行都在争"点发送后的第一秒体验"：输入框必须先清空、气泡必须立刻上屏，
 * 任何网络请求（历史拉取）都排在后面。所以它从发送控制器里独立出来，
 * 让"什么时候上屏"和"怎么发请求"的改动互不牵连。
 */
internal class SendPreflight(
    private val uiState: MutableStateFlow<ChatUiState>,
    private val chatRepository: ChatRepository,
    private val sessionController: ChatSessionController,
    private val guard: ChatUiWriteGuard,
    /** 预览写入（由门面注入，保证全 App 只有一个写入点）。 */
    private val writePreview: suspend (message: Message, profileFilename: String?) -> Unit
) {
    companion object {
        private const val TAG = "SendPreflight"

        /**
         * 请求体里携带的历史窗口上限（条数）。
         *
         * 这个窗口会原样作为 `history_override` 上传，所以它直接决定请求体大小：
         * 实测最近 200 条的文本量是 44-95KB。内网直连无所谓，但走 Cloudflare Tunnel 时
         * 这段上传要 0.75s 以上，叠加 TLS 握手就是用户感知的「点发送卡 2-3 秒」。
         */
        private const val HISTORY_WINDOW_MESSAGES = 200

        /**
         * 真正上传的历史字符预算。
         *
         * 后端 context_budget 实际只会用到 24000 字符或 18 条 / 6000 字符，
         * 超出部分会被直接截断 —— 砍掉的全是白传的字节。
         */
        private const val HISTORY_BUDGET_CHARS = 20_000

        /** 至少保留的条数：消息很长时不至于把窗口削得过薄。 */
        private const val HISTORY_MIN_MESSAGES = 12

        /**
         * 正在「发送预检」中的会话集合。
         *
         * 点下发送到请求真正发出之间有一段预检（persona 切换、历史窗口组装、写库），
         * 这段窗口里界面本来不会变，用户很容易以为没点上而重复点击。
         * 只锁预检窗口，不锁生成过程：生成期间用户主动再发一条是允许的（后端会 cancel 上一条）。
         */
        private val inFlightPreflight: MutableSet<String> = ConcurrentHashMap.newKeySet()
    }

    /** 预检产物：已落库的用户消息、它之前的正文窗口、本次请求冻结的 persona。 */
    data class PreparedSend(
        val userMessage: Message,
        val prefixHistory: List<Message>,
        val profileFilename: String?
    )

    /**
     * 尝试占用该会话的预检窗口。
     *
     * @return 去重键；返回 null 表示同一次点击已经在处理中，本次应直接忽略
     */
    fun tryAcquire(sessionId: String?): String? {
        // key 取点击瞬间的会话。预检内部换 persona 不会换 role session，
        // 所以这个 key 在整个预检窗口内都稳定。
        val key = sessionId ?: SendRuntime.DEFAULT_SEND_KEY
        return if (inFlightPreflight.add(key)) key else null
    }

    fun release(key: String) {
        inFlightPreflight.remove(key)
    }

    /**
     * 执行预检。
     *
     * 失败时把正文写回输入框并置 error，返回 null；调用方只在拿到非 null 时才进入生成。
     * 入口先把输入框清空（立刻给用户「发出去了」的反馈），所以这里的每个失败分支
     * 都必须把原文还回去，不能吞掉用户打的字。
     */
    suspend fun prepare(
        entrySessionId: String?,
        pendingText: String,
        imageUrl: String?,
        videoUrl: String?,
        attachments: List<ChatAttachment>,
        generateMessageId: () -> String
    ): PreparedSend? {
        // 立刻清空输入框：用户点完发送就该看到「已经发出去了」的反馈。
        // 必须放在整条链路最前面 —— 下面的预检在界面上本来什么都不会变。
        guard.withUiIfActive(entrySessionId) {
            uiState.update { it.copy(inputText = "", error = null) }
        }
        try {
            sessionController.consumePendingSwitchIfNeeded()
        } catch (e: Exception) {
            restoreInputOnFailure(pendingText, "切换人设失败: ${e.message}")
            return null
        }

        val sessionId = sessionController.conversationSessionId
        if (sessionId.isNullOrBlank()) {
            restoreInputOnFailure(pendingText, "聊天记录尚未加载，请稍后重试")
            return null
        }
        val profileFilename = sessionController.conversationProfileFilename
            ?: sessionController.profileFilenameForSessionOwned(sessionId)
        // 乐观上屏、落库、写列表预览全部前置到任何网络请求和重查询之前。
        // parentId 先用屏幕上最后一条：落库时 withExistingParent 会校验父节点是否
        // 还在，不在就回落到活跃路径尾部，不会留下悬空父链。
        val existingBeforeSend = uiState.value.messages
        val parentHint = existingBeforeSend.lastOrNull()?.id
        val userMessage = Message(
            id = generateMessageId(),
            text = pendingText,
            isUser = true,
            timestamp = System.currentTimeMillis(),
            messageType = when {
                !videoUrl.isNullOrBlank() -> "video"
                attachments.isNotEmpty() && attachments.all { it.kind == ChatAttachmentKind.IMAGE } &&
                    attachments.size == 1 -> "image"
                attachments.isNotEmpty() -> "attachment"
                !imageUrl.isNullOrBlank() -> "image"
                else -> "text"
            },
            imageUrl = imageUrl ?: attachments.firstOrNull {
                it.kind == ChatAttachmentKind.IMAGE
            }?.url,
            videoUrl = videoUrl,
            attachments = attachments,
            sessionId = sessionId,
            parentId = parentHint
        )
        // 乐观上屏：气泡先插进 uiState，不等 Room 回流。
        // uiState.messages 由消息 Flow 整体覆盖（ChatSessionObserver.observeMessages），
        // 长会话下那次回流要重算整棵消息树，等它才上屏就是「点发送卡一下」的体感。
        guard.withUiIfActive(sessionId) {
            uiState.update { state ->
                state.copy(
                    messages = state.messages + userMessage,
                    // 点下去就转圈：请求还没发出去，但"已经被受理"必须立刻可见。
                    isTyping = true,
                    showTypingIndicator = true
                )
            }
        }
        // 首次进入这个会话时，远端历史必须先拉下来再落库。
        // loadHistoryFromApi 用"本地已有消息就跳过"判定要不要走 API，用户消息一旦
        // 先落库，它就会把整段远端历史当成"已有会话"直接跳过 —— 这条会话的上下文
        // 从此永久缺前半段。这一步排在乐观上屏之后，所以不影响"点一下就看见气泡"。
        if (existingBeforeSend.isEmpty()) {
            runCatching { chatRepository.loadHistoryFromApi(sessionId).getOrThrow() }
                .onFailure { Log.w(TAG, "首次会话历史拉取失败，本轮上下文可能不完整: ${it.message}") }
        }
        val insertResult = chatRepository.insertMessageVariant(userMessage)
        if (insertResult.isFailure) {
            // 写库失败就把乐观插入撤回，避免界面上留一条实际不存在的消息
            guard.withUiIfActive(sessionId) {
                uiState.update { state ->
                    state.copy(
                        messages = state.messages.filterNot { it.id == userMessage.id },
                        isTyping = false,
                        showTypingIndicator = false
                    )
                }
            }
            restoreInputOnFailure(
                pendingText,
                "消息保存失败: ${insertResult.exceptionOrNull()?.message}",
                sessionId
            )
            return null
        }
        writePreview(userMessage, profileFilename)

        // 正文窗口只服务本轮上下文，可以比气泡晚：上滑、缩小页面窗口也不能改变
        // 下一轮的上下文来源（所以按固定窗口取，不用 uiState.messages）。
        //
        // 失败不再把消息撤回：此刻消息已经落库、用户也看见了，撤回只会让人以为
        // "发了又没了"。降级成"本地能读多少读多少"，最差是本轮上下文薄一点。
        val prefixHistory = try {
            chatRepository.loadHistoryFromApi(sessionId).getOrThrow()
            loadContextWindow(sessionId, userMessage.id)
        } catch (e: Exception) {
            Log.w(TAG, "读取聊天记录失败，按本地窗口继续发送: ${e.message}")
            runCatching { loadContextWindow(sessionId, userMessage.id) }.getOrDefault(emptyList())
        }
        return PreparedSend(userMessage, prefixHistory, profileFilename)
    }

    /**
     * 取消发生得太早（预检阶段）时的兜底收尾。
     *
     * 只做**幂等**的两件事：
     * 1. 关掉打字指示器 —— 图片/视频路径在进发送前就置了 isTyping = true，
     *    预检被取消时没人再把它关掉，界面会永远卡在「正在输入」。
     * 2. 输入框仍为空且消息尚未落库时把原文还回去 —— 预检第一步就清了输入框，
     *    取消后用户打的字会凭空消失。已落库就不还：那条消息是用户真实发出去的。
     *
     * 刻意不碰消息树：取消点不同，用户气泡可能已插入也可能没有，无法可靠判断该不该撤回。
     * 那条消息是用户真实发过的内容，留在会话里比猜着删掉更安全。
     *
     * @param selfJob 本轮自己的 Job。收尾前要拿它和运行时登记表对一下：若已经不是自己，
     *   说明同一会话起了新一轮，界面状态现在归那一轮管 —— 再关打字指示器会把
     *   新一轮的「正在输入」抹掉（用户看到"发了没反应"）。
     */
    suspend fun rescueCancelledSend(
        sessionId: String?,
        selfJob: Job?,
        originalText: String?,
        restoreText: Boolean
    ) {
        guard.withUiIfActive(sessionId) {
            uiState.update { state ->
                if (!SendRuntime.isCurrentJob(sessionId, selfJob)) return@update state
                state.copy(
                    isTyping = false,
                    showTypingIndicator = false,
                    inputText = if (restoreText && originalText != null && state.inputText.isBlank()) {
                        originalText
                    } else {
                        state.inputText
                    }
                )
            }
        }
    }

    /**
     * 取本轮请求的正文窗口，并剔掉刚乐观插入的这条用户消息。
     *
     * 上屏提到窗口查询之前以后，窗口里必然已经包含这条消息；不去掉就会在本轮
     * `history_override` 里出现两次（一次是历史、一次是本次输入），后端看到重复发言。
     */
    private suspend fun loadContextWindow(
        sessionId: String,
        excludeMessageId: String
    ): List<Message> =
        trimHistoryForRequest(
            chatRepository.observeMessageWindow(sessionId, HISTORY_WINDOW_MESSAGES).first()
                .messages
                .filterNot { it.id == excludeMessageId }
        )

    /**
     * 把要上传的历史裁到后端上下文预算之内。
     *
     * 从最新往回累积，直到接近 [HISTORY_BUDGET_CHARS] 为止；至少保留
     * [HISTORY_MIN_MESSAGES] 条。保留的是最新的若干条（而不是最早的），
     * 与后端预算逻辑一致 —— 它同样只保留最近的内容，多传的部分会被截断。
     */
    private fun trimHistoryForRequest(history: List<Message>): List<Message> {
        if (history.isEmpty()) return history

        var chars = 0
        var taken = 0
        for (message in history.asReversed()) {
            val next = chars + message.text.length
            if (taken >= HISTORY_MIN_MESSAGES && next > HISTORY_BUDGET_CHARS) break
            chars = next
            taken++
        }
        return history.takeLast(taken)
    }

    /**
     * 预检失败时把正文写回输入框。
     *
     * 发送入口会先把输入框清空（好让用户立刻看到「已经发出去了」），所以任何
     * 「消息还没落库就退出」的分支都必须把原文还回去，否则用户打的字凭空消失。
     * 只在输入框仍为空时回填：预检期间用户可能已经重新开始输入，不能覆盖新的内容。
     */
    private suspend fun restoreInputOnFailure(
        text: String,
        error: String,
        sessionId: String? = null
    ) {
        guard.withUiIfActive(sessionId) {
            uiState.update {
                it.copy(inputText = if (it.inputText.isBlank()) text else it.inputText, error = error)
            }
        }
    }
}
