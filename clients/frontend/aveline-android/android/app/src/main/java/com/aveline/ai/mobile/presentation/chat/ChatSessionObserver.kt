package com.aveline.ai.mobile.presentation.chat

import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.StreamEvent
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.data.remote.api.WebSocketMessage
import com.aveline.ai.mobile.domain.models.Emotion
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.domain.repository.SessionRepository
import com.aveline.ai.mobile.services.media.LocalMediaStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.emitAll
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 负责"会话与消息流"的观察与事件分发。
 *
 * 从 ChatViewModel 拆出，职责：
 * - [observeCurrentSession]：监听当前会话变化并写入 uiState
 * - [observeMessages]：随会话切换加载对应 session 的历史消息（消息按角色隔离的关键）
 * - [observeConnectionState]：监听 WebSocket 连接状态并更新 loadingState
 * - [observeWebSocketMessages]：分发 WebSocket 消息到各子模块（文本/图片落库、
 *   flush、peer chat、emotion 等）
 * - 会话操作：createNewSession / switchSession / clearHistory
 *
 * @param scope ViewModel 的协程作用域
 * @param uiState UI 状态流，当前会话/消息/连接状态写入此流
 * @param chatRepository 聊天仓库
 * @param sessionRepository 会话仓库
 * @param webSocketManager WebSocket 管理器
 * @param appPreferences 全局偏好（switchSession 时改写 currentSessionId）
 * @param onMessagesLoaded 消息列表变化回调（供 VM 更新列表预览）
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ChatSessionObserver(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val chatRepository: ChatRepository,
    private val sessionRepository: SessionRepository,
    private val webSocketManager: WebSocketManager,
    private val appPreferences: AppPreferences,
    private val onMessagesLoaded: (List<com.aveline.ai.mobile.domain.models.Message>) -> Unit,
    private val incomingHandler: ChatIncomingMessageHandler,
    private val flushManager: ChatFlushManager,
    private val peerChatHandler: ChatPeerChatHandler,
    /**
     * 这个 session 是否属于本聊天页的角色。
     *
     * `observeCurrentSession()` 是**全局**的：任何存活的 ChatViewModel 都会收到
     * 每个会话的切换与新消息。不加这层过滤，页 A 会拿页 B 的消息刷新自己的
     * uiState 与列表预览 —— 两个角色的副标题变成同一段话就是这么来的。
     * 默认放行，兼容单测与尚未确定角色的首帧。
     */
    private val isOwnedSession: (String) -> Boolean = { true },
    /**
     * 媒体本地仓库：本窗口历史消息里的图片/表情包/视频进页面即后台落盘，
     * 不再依赖"滚到屏幕上"才触发下载。可空 + 默认值：单测直接构造时不传。
     */
    private val localMediaStore: LocalMediaStore? = null
) {
    companion object {
        private const val TAG = "ChatSessionObserver"
        private const val HISTORY_PAGE_SIZE = 50

        /**
         * 这些都属于连接生命周期里的可恢复传输异常：WebSocketManager 会自动重连，
         * 不应再把底层 socket 文案直接弹给用户。配置/鉴权/协议错误不在此列表，仍正常上屏。
         */
        private val RECOVERABLE_WS_ERROR_MARKERS = listOf(
            "connection reset",
            "connectionresetexception",
            "broken pipe",
            "socket closed",
            "connection closed",
            "software caused connection abort",
            "unexpected end of stream",
            "end of stream",
            "network is unreachable",
            "failed to connect",
            "connect timed out",
            "read timed out",
            "timeout",
            "timed out"
        )
    }

    private val historyWindowSize = MutableStateFlow(HISTORY_PAGE_SIZE)

    fun loadOlderMessages() {
        if (uiState.value.hasOlderMessages) historyWindowSize.update { it + HISTORY_PAGE_SIZE }
    }

    /** 开始监听：当前会话 + 消息流 + 连接状态 + 动作描写开关 + WS 事件。 */
    fun start() {
        observeCurrentSession()
        observeMessages()
        observeConnectionState()
        observeStageDirectionSetting()
        observeWebSocketMessages()
    }

    /**
     * 跟随设置页的「动作描写」开关。
     *
     * 订阅 Flow 而不是在渲染时读一次：用户从设置页返回聊天页时开关可能已经变了，
     * 靠 `uiState` 里的一次性快照会让已上屏的消息仍然保持旧的括号渲染。
     */
    private fun observeStageDirectionSetting() {
        scope.launch {
            appPreferences.stageDirectionEnabledFlow.collect { enabled ->
                uiState.update { it.copy(stageDirectionEnabled = enabled) }
            }
        }
    }

    private fun observeCurrentSession() {
        scope.launch {
            sessionRepository.observeCurrentSession()
                .catch { e ->
                    uiState.update { it.copy(error = "加载会话失败: ${e.message}") }
                }
                .collect { session ->
                    if (session?.id != appPreferences.currentSessionId) return@collect
                    uiState.update { it.copy(currentSession = session) }
                }
        }
    }

    private fun observeMessages() {
        scope.launch {
            // 记录当前 flow 对应的 sessionId，用于 collect 归属校验：
            // flatMapLatest 取消旧 flow 是协作式的，切换瞬间旧 flow 的残留消息
            // 可能仍到达 collect，只有与当前 session 匹配的消息才允许上屏/写预览。
            var expectedSessionId: String? = null
            sessionRepository.observeCurrentSession()
                .filterNotNull()
                .distinctUntilChanged { old, new -> old.id == new.id }
                .flatMapLatest { session ->
                    expectedSessionId = session.id
                    historyWindowSize.value = HISTORY_PAGE_SIZE
                    Log.d(TAG, "observeMessages: 会话切换，加载 sessionId=${session.id}")
                    // 切换会话立即清空旧消息，避免切换瞬间显示上一个角色的聊天记录
                    // （新 flow 的数据到达后会自动填充）
                    if (session.id == appPreferences.currentSessionId) {
                        uiState.update { it.copy(currentSession = session, messages = emptyList(), hasOlderMessages = false) }
                    }
                    // 使用 flow 确保取消传播，而不是嵌套 launch
                    flow {
                        chatRepository.loadHistoryFromApi(session.id)
                        emitAll(historyWindowSize.flatMapLatest { limit ->
                            chatRepository.observeMessageWindow(session.id, limit)
                                .map { session.id to it }
                        })
                    }
                }
                .catch { e ->
                    Log.e(TAG, "observeMessages: 加载消息失败 - ${e.message}", e)
                    uiState.update { it.copy(error = "加载消息失败: ${e.message}") }
                }
                .collect { (sourceSessionId, window) ->
                    val messages = window.messages
                    // 归属过滤：不属于本页角色的会话一律不处理（不刷新 UI、不写预览）。
                    // 全局 currentSessionId 在多聊天页并存时会指向别的角色，
                    // 下面三条判据都是"与全局值比对"，拦不住这种串台。
                    if (!isOwnedSession(sourceSessionId)) {
                        Log.d(TAG, "observeMessages: 跳过其他角色的会话 $sourceSessionId")
                        return@collect
                    }
                    // 即使结果为空，也必须携带来源，不能让旧会话空快照清掉新页面。
                    if (sourceSessionId != expectedSessionId ||
                        sourceSessionId != appPreferences.currentSessionId ||
                        sourceSessionId != uiState.value.currentSession?.id
                    ) return@collect
                    // 竞态防护：旧 flow 的残留消息（上一个角色的记录）在切换瞬间可能
                    // 仍到达 collect。校验消息归属，不属于当前会话的一律丢弃，
                    // 既不上屏也不写预览（修复"先显示上一个人记录再刷新消失"与
                    // "Aveline 预览显示卡夫卡消息"两个串台现象）。
                    if (expectedSessionId != null && messages.any { it.sessionId != null && it.sessionId != expectedSessionId }) {
                        Log.w(TAG, "observeMessages: 丢弃不属于当前会话($expectedSessionId)的残留消息 ${messages.size} 条")
                        return@collect
                    }
                    Log.d(TAG, "observeMessages: 从数据库加载 ${messages.size} 条消息")
                    uiState.update { it.copy(messages = messages, hasOlderMessages = window.hasOlder) }

                    // 历史媒体预热：本窗口的图片/表情包/视频/附件在后台顺序落盘（已落盘的跳过）。
                    // 后端离线后再进页面，表情包能直接读本地文件，而不是等网络超时一直转圈。
                    localMediaStore?.prefetchAll(
                        messages.flatMap { msg ->
                            listOfNotNull(msg.imageUrl, msg.videoUrl) + msg.attachments.map { it.url }
                        }
                    )

                    // 写入最后一条消息预览到 PersonaLocalMeta，供会话列表页副标题使用。
                    // 预览归属以"消息自身的 sessionId"为准（见 ChatIncomingMessageHandler），
                    // 即使发生竞态，也只会写到消息真正所属的角色上。
                    onMessagesLoaded(messages)

                    if (messages.isNotEmpty()) {
                        uiState.update { it.copy(loadingState = LoadingState.Loaded(messages)) }
                    } else {
                        val connectionState = uiState.value.connectionState
                        when (connectionState) {
                            WebSocketManager.ConnectionState.CONNECTED -> {
                                uiState.update { it.copy(loadingState = LoadingState.Loaded(emptyList())) }
                            }
                            WebSocketManager.ConnectionState.CONNECTING -> {
                                uiState.update { it.copy(loadingState = LoadingState.Loading) }
                            }
                            else -> {
                                uiState.update { it.copy(loadingState = LoadingState.NotLoaded) }
                            }
                        }
                    }
                }
        }
    }

    private fun observeConnectionState() {
        scope.launch {
            webSocketManager.connectionState.collect { state ->
                uiState.update { it.copy(connectionState = state) }

                when (state) {
                    WebSocketManager.ConnectionState.CONNECTING -> {
                        uiState.update { it.copy(loadingState = LoadingState.Loading) }
                    }
                    WebSocketManager.ConnectionState.CONNECTED -> {
                        val currentMessages = uiState.value.messages
                        if (currentMessages.isNotEmpty()) {
                            uiState.update { it.copy(loadingState = LoadingState.Loaded(currentMessages)) }
                        } else {
                            uiState.update { it.copy(loadingState = LoadingState.Loaded(emptyList())) }
                        }
                    }
                    WebSocketManager.ConnectionState.DISCONNECTED -> {
                        val currentMessages = uiState.value.messages
                        if (currentMessages.isEmpty()) {
                            uiState.update { it.copy(loadingState = LoadingState.NotLoaded) }
                        }
                    }
                }
            }
        }
    }

    private fun observeWebSocketMessages() {
        scope.launch {
            webSocketManager.messages.collect { message ->
                when (message) {
                    is WebSocketMessage.TextMessage -> {
                        incomingHandler.handleTextMessage(message)
                    }
                    is WebSocketMessage.ResponseChunk -> {
                        flushManager.handleResponseChunk(message)
                    }
                    is WebSocketMessage.ResponseDone -> {
                        flushManager.onResponseDone()
                    }
                    is WebSocketMessage.ResponseReset -> {
                        // AI 开始调用工具: 清空当前正在生成的临时消息,不影响历史消息
                        flushManager.onResponseReset()
                    }
                    is WebSocketMessage.EmotionUpdate -> {
                        val emotion = Emotion(
                            primary = message.primary,
                            intensity = message.intensity,
                            colors = message.colors
                        )
                        uiState.update { it.copy(currentEmotion = emotion) }
                    }
                    is WebSocketMessage.Error -> {
                        // 后端业务错误（带 error_code）必须原样提示：文案里即使含
                        // timeout / connection reset，那也是"上游模型失败"，不是可
                        // 自动恢复的本端传输抖动。吞掉就成了「AI 不回复也不报错」。
                        val isBackendError = !message.errorCode.isNullOrBlank()
                        if (!isBackendError && isRecoverableWebSocketTransportError(message.message)) {
                            // 掉线本身由 connectionState 表达，WebSocketManager 会后台重连。
                            // 这里只结束可能残留的“正在输入”状态，不再弹 connection reset 等 Snackbar。
                            Log.d(TAG, "忽略可自动恢复的 WebSocket 传输错误: ${message.message}")
                            uiState.update {
                                it.copy(
                                    isTyping = false,
                                    showTypingIndicator = false
                                )
                            }
                        } else {
                            uiState.update {
                                it.copy(
                                    // 后端的 error_code 一并展示，便于区分敏感拦截/限流/超时
                                    error = StreamEvent.Error(
                                        message = message.message,
                                        errorCode = message.errorCode,
                                    ).describe(),
                                    isTyping = false,
                                    showTypingIndicator = false
                                )
                            }
                        }
                    }
                    is WebSocketMessage.ImageResult -> {
                        incomingHandler.handleImageResultMessage(message)
                    }
                    is WebSocketMessage.VideoResult -> {
                        incomingHandler.handleVideoResultMessage(message)
                    }
                    is WebSocketMessage.LifeStatusUpdate -> {
                        // 由 StatusRepository 处理
                    }
                    is WebSocketMessage.RitualEvent -> {
                        // 仪式事件，可后续扩展
                    }
                    is WebSocketMessage.SpontaneousReaction -> {
                        // 自发反应，可后续扩展
                    }
                    is WebSocketMessage.PeerChatMessage -> {
                        peerChatHandler.handlePeerChatMessage(message)
                    }
                    is WebSocketMessage.PeerChatScriptStart -> {
                        peerChatHandler.handlePeerChatScriptStart(message)
                    }
                    is WebSocketMessage.PeerChatScriptEnd -> {
                        peerChatHandler.handlePeerChatScriptEnd(message)
                    }
                    else -> Unit
                }
            }
        }
    }

    private fun isRecoverableWebSocketTransportError(message: String): Boolean {
        val normalized = message.lowercase()
        return RECOVERABLE_WS_ERROR_MARKERS.any { marker -> normalized.contains(marker) }
    }

    /** 创建新会话并切换到它。 */
    fun createNewSession(title: String = "新对话") {
        scope.launch {
            uiState.update { it.copy(isLoading = true) }
            val result = sessionRepository.createSession(title)
            result.fold(
                onSuccess = { session ->
                    uiState.update {
                        it.copy(currentSession = session, messages = emptyList(), isLoading = false)
                    }
                },
                onFailure = { e ->
                    uiState.update {
                        it.copy(error = "创建会话失败: ${e.message}", isLoading = false)
                    }
                }
            )
        }
    }

    /** 切换到指定会话。 */
    fun switchSession(sessionId: String) {
        appPreferences.currentSessionId = sessionId
        flushManager.clear()
    }

    /** 清空当前会话历史。 */
    fun clearHistory() {
        val sessionId = uiState.value.currentSession?.id ?: return
        scope.launch(kotlinx.coroutines.Dispatchers.IO) {
            runCatching {
                chatRepository.clearHistory(sessionId)
            }.onFailure { e ->
                Log.e(TAG, "清空历史失败", e)
                uiState.update { it.copy(error = "清空历史失败: ${e.message}") }
            }
        }
    }
}
