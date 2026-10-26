package com.aveline.ai.mobile.presentation.status

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.data.repository.StatusRepositoryImpl
import com.aveline.ai.mobile.domain.repository.StatusRepository
import com.aveline.ai.mobile.domain.repository.ToolsRepository
import com.aveline.ai.mobile.presentation.status.ui.StatusUiState
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.jsonObject
import javax.inject.Inject

/**
 * 状态面板 ViewModel
 *
 * 功能：
 * - 生命状态显示
 * - 情绪状态显示
 * - 连接状态显示
 * - 系统时钟同步
 *
 * Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
 */
@HiltViewModel
class StatusViewModel @Inject constructor(
    private val statusRepository: StatusRepository,
    private val statusRepositoryImpl: StatusRepositoryImpl,
    private val toolsRepository: ToolsRepository,
    private val webSocketManager: WebSocketManager
) : ViewModel() {

    private val _uiState = MutableStateFlow(StatusUiState())
    val uiState: StateFlow<StatusUiState> = _uiState.asStateFlow()

    /**
     * 系统时钟单独一个流。
     *
     * 以前时钟塞在 [StatusUiState] 里，每秒改一次就把整棵伴侣详情面板重组合一遍；
     * 而伴侣详情面板常驻在聊天页的组合树里，于是聊天页每秒也跟着重组一次，
     * 用户滑动时更容易掉帧。拆出来之后，只有真正显示时钟的地方才会重组。
     */
    private val _clock = MutableStateFlow("")
    val clock: StateFlow<String> = _clock.asStateFlow()

    private var clockJob: Job? = null
    private var emotionJob: Job? = null
    private var statusRefreshJob: Job? = null
    private var statusRefreshPersona: String? = null
    private var statusRefreshRequestId: Long = 0L

    /** 当前正在查看的 persona 文件名（来自聊天会话/伴侣面板选择，纯只读）；为 null 表示用后端默认 */
    @Volatile
    private var currentProfileFilename: String? = null

    @Volatile
    private var currentConversationId: String? = null

    init {
        observeConnection()
        observeEmotion()
        startClock()
    }

    /**
     * 设置“正在查看的角色”对应的 persona 文件名（纯只读查询，不切对话人设）。
     * 由 ChatScreen 在聊天进入 / 面板内选版本时调用，随后按该角色加载生命状态。
     */
    fun setControlContext(filename: String?, conversationId: String?) {
        val normalizedFilename = filename?.takeIf { it.isNotBlank() }
        val normalizedConversationId = conversationId?.takeIf { it.isNotBlank() }
        if (
            normalizedFilename == currentProfileFilename &&
            normalizedConversationId == currentConversationId
        ) return
        currentProfileFilename = normalizedFilename
        currentConversationId = normalizedConversationId

        // 角色 / 会话边界变化不能继续读一分钟缓存；直接拉一次当前角色权威状态。
        // 与详情面板 visible 首刷共用同一个去重入口，因此同帧触发不会重复请求。
        refreshStatusForPersona(normalizedFilename)
    }

    /** 兼容仅更新查看角色的旧调用。 */
    fun setViewingPersona(filename: String) {
        setControlContext(filename, currentConversationId)
    }

    /**
     * 加载生命状态（按当前角色 scope）。
     *
     * 保留给非强制刷新场景使用；角色切换与详情页首刷必须走 [refreshStatusForPersona]。
     */
    fun loadStatus() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }

            val result = statusRepository.getLifeStatus(persona = currentProfileFilename)

            result.fold(
                onSuccess = { status ->
                    _uiState.update {
                        it.copy(
                            lifeStatus = status,
                            isLoading = false
                        )
                    }
                },
                onFailure = { e ->
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            error = "加载失败: ${e.message}"
                        )
                    }
                }
            )

            loadSystemStats()
        }
    }

    /**
     * 刷新当前控制上下文的状态（静默刷新）。
     *
     * 命中仓库的一分钟缓存时零网络请求。用于"打开伴侣详情""切到日程页"这类
     * **不该让用户等**的场景：面板先用缓存渲染，再在后台悄悄刷新。
     */
    fun refreshStatus() {
        refreshStatusForPersona(currentProfileFilename)
    }

    /**
     * 强制刷新当前控制上下文的状态（绕过缓存，直接走网络）。
     *
     * 只给用户主动点"刷新"的场景用。
     */
    fun forceRefreshStatus() {
        refreshStatusForPersona(currentProfileFilename, force = true)
    }

    /**
     * 刷新指定 persona 的状态。
     *
     * 详情面板打开时显式传 [persona]，避免 Compose 可见态更新与 ChatScreen 的
     * control context 更新处在同一帧时误刷上一个角色。相同 persona 已有请求在飞时直接复用；
     * 目标 persona 改变时让旧请求自然结束但丢弃旧结果，防止旧响应晚到覆盖新角色状态。
     *
     * @param force true 表示跳过仓库缓存强制走网络（用户主动刷新）；false 表示缓存优先。
     */
    fun refreshStatusForPersona(persona: String?, force: Boolean = false) {
        val targetPersona = persona?.takeIf { it.isNotBlank() } ?: currentProfileFilename
        // 先用仓库里的上次权威状态渲染，再去拉网络：本 ViewModel 随聊天页重建，
        // 不播种就会在每次进详情时留下“空白 + 等一次网络”的空窗。
        seedLifeStatusFromCache(targetPersona)
        val runningJob = statusRefreshJob
        if (runningJob?.isActive == true && statusRefreshPersona == targetPersona) {
            return
        }

        statusRefreshPersona = targetPersona
        statusRefreshRequestId += 1L
        val requestId = statusRefreshRequestId
        statusRefreshJob = viewModelScope.launch {
            // 已经有数据时不做整块 loading：缓存优先的刷新不该让面板闪成转圈。
            val showLoading = _uiState.value.lifeStatus == null
            if (showLoading) {
                _uiState.update { it.copy(isLoading = true, error = null) }
            }

            val result = if (force) {
                statusRepositoryImpl.forceRefreshLifeStatus(persona = targetPersona)
            } else {
                statusRepository.getLifeStatus(persona = targetPersona)
            }
            // 切角色后旧请求即使更晚返回，也不能覆盖最新角色的状态。
            if (requestId != statusRefreshRequestId) return@launch

            result.fold(
                onSuccess = { status ->
                    _uiState.update {
                        it.copy(
                            lifeStatus = status,
                            isLoading = false
                        )
                    }
                },
                onFailure = { e ->
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            error = "刷新失败: ${e.message}"
                        )
                    }
                }
            )

            loadSystemStats()
        }
    }

    /**
     * 先用单例仓库里的上次权威状态把 UI 渲染出来（stale-while-revalidate）。
     *
     * 仓库缓存跨页面存活、也会被 WebSocket 推送刷新，所以它常比本 ViewModel 的 UI 状态更新。
     * 只有缓存与当前查看 persona 完全一致时才采用，避免切角色后显示上一个角色的状态。
     */
    private fun seedLifeStatusFromCache(persona: String?) {
        val cached = statusRepositoryImpl.cachedLifeStatus.value ?: return
        if (cached.scope != persona) return
        // 设备跨天后缓存里是更早一天的日程：先渲染会让日程页闪出旧的槽位与「正在进行」，
        // 直接不播种，让下面这次刷新从接口取今天的计划。判断口径与仓库缓存一致，
        // 只比设备自然日是否翻页，不拿后端计划日期与设备日期直接比。
        if (statusRepositoryImpl.isCachedPlanStaleForDeviceDay()) return
        _uiState.update { state ->
            val current = state.lifeStatus
            if (current != null && current.timestamp >= cached.timestamp) state
            else state.copy(lifeStatus = cached)
        }
    }

    fun wakeCompanion() = runCompanionAction("唤醒失败") {
        statusRepository.wakeCompanion(currentProfileFilename, currentConversationId)
    }

    fun interruptCompanion() = runCompanionAction("打断失败") {
        statusRepository.interruptCompanion(currentProfileFilename, currentConversationId)
    }

    fun skipCompanionActivity() = runCompanionAction("跳过失败") {
        statusRepository.skipCompanionActivity(currentProfileFilename, currentConversationId)
    }

    private fun runCompanionAction(
        fallbackError: String,
        action: suspend () -> Result<String>
    ) {
        if (_uiState.value.isActionRunning) return
        viewModelScope.launch {
            _uiState.update {
                it.copy(isActionRunning = true, actionMessage = null, error = null)
            }
            action().fold(
                onSuccess = { message ->
                    _uiState.update {
                        it.copy(isActionRunning = false, actionMessage = message)
                    }
                    statusRepositoryImpl.forceRefreshLifeStatus(currentProfileFilename)
                        .onSuccess { status ->
                            _uiState.update { it.copy(lifeStatus = status) }
                        }
                },
                onFailure = { error ->
                    _uiState.update {
                        it.copy(
                            isActionRunning = false,
                            error = "$fallbackError: ${error.message ?: "未知错误"}"
                        )
                    }
                }
            )
        }
    }

    private fun loadSystemStats() {
        viewModelScope.launch {
            toolsRepository.getSystemStats().onSuccess { statsElement ->
                val stats = statsElement?.jsonObject
                _uiState.update { it.copy(systemStats = stats) }
            }.onFailure {
                // 保持安静失败，状态页仍可展示其他实时数据
            }
        }
    }

    /**
     * 观察连接状态
     */
    private fun observeConnection() {
        viewModelScope.launch {
            webSocketManager.connectionState.collect { state ->
                _uiState.update {
                    it.copy(connected = state == WebSocketManager.ConnectionState.CONNECTED)
                }
            }
        }
    }

    /**
     * 观察情绪变化
     */
    private fun observeEmotion() {
        emotionJob = viewModelScope.launch {
            statusRepository.observeEmotion().collect { emotion ->
                _uiState.update { it.copy(emotion = emotion) }
            }
        }
        // Also observe emotionMix from WebSocket EmotionUpdate messages directly
        viewModelScope.launch {
            webSocketManager.messages.collect { message ->
                when (message) {
                    is com.aveline.ai.mobile.data.remote.api.WebSocketMessage.EmotionUpdate -> {
                        if (message.emotionMix.isNotEmpty()) {
                            _uiState.update { it.copy(emotionMix = message.emotionMix) }
                        }
                    }
                    is com.aveline.ai.mobile.data.remote.api.WebSocketMessage.ConnectionEstablished -> {
                        Log.d("StatusViewModel", "Connection established: heartbeat=${message.heartbeatInterval}s, reconnect=${message.reconnectSupported}")
                    }
                    is com.aveline.ai.mobile.data.remote.api.WebSocketMessage.ReconnectSync -> {
                        // Sync emotion and life status from reconnect
                        message.currentModel?.let { model ->
                            Log.d("StatusViewModel", "Reconnect sync: currentModel=$model")
                        }
                        message.lifeStatus?.let { status ->
                            val syncedLifeStatus = com.aveline.ai.mobile.domain.models.LifeStatus(
                                health = status["health"] ?: 1.0f,
                                hunger = status["hunger"] ?: 0f,
                                happiness = status["mood_score"] ?: 1.0f,
                                energy = status["energy"] ?: 1.0f,
                                timestamp = System.currentTimeMillis(),
                                scope = _uiState.value.lifeStatus?.scope,
                                activity = _uiState.value.lifeStatus?.activity ?: "idle",
                                activityChatEligible = _uiState.value.lifeStatus?.activityChatEligible ?: true,
                                replyMode = _uiState.value.lifeStatus?.replyMode ?: "immediate",
                                replyDelayMinSeconds = _uiState.value.lifeStatus?.replyDelayMinSeconds,
                                replyDelayMaxSeconds = _uiState.value.lifeStatus?.replyDelayMaxSeconds,
                                isSleeping = _uiState.value.lifeStatus?.isSleeping ?: false,
                                sleepPhase = _uiState.value.lifeStatus?.sleepPhase,
                                dailyPlan = _uiState.value.lifeStatus?.dailyPlan
                            )
                            _uiState.update { it.copy(lifeStatus = syncedLifeStatus) }
                        }
                    }
                    else -> Unit
                }
            }
        }
    }

    /**
     * 启动时钟
     */
    private fun startClock() {
        clockJob = viewModelScope.launch {
            while (true) {
                val now = java.time.LocalDateTime.now()
                val formatted = now.format(
                    java.time.format.DateTimeFormatter.ofPattern("HH:mm:ss")
                )
                _clock.value = formatted
                delay(1000)
            }
        }
    }

    /**
     * 清除错误
     */
    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }

    override fun onCleared() {
        super.onCleared()
        clockJob?.cancel()
        emotionJob?.cancel()
        statusRefreshJob?.cancel()
    }
}
