package com.aveline.ai.mobile.presentation.settings

import android.content.Context
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.os.Build
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.domain.repository.ContextRepository
import com.aveline.ai.mobile.services.AvelineForegroundServiceV2
import com.aveline.ai.mobile.services.endpoint.EndpointResolver
import com.aveline.ai.mobile.services.endpoint.probeCandidates
import com.aveline.ai.mobile.services.endpoint.resolver.EndpointCandidateProbe
import com.aveline.ai.mobile.services.endpoint.resolver.EndpointChannel
import com.aveline.ai.mobile.services.endpoint.resolver.ResolvedEndpoint
import com.aveline.ai.mobile.services.worker.DataSyncManager
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * 设置界面 ViewModel。
 *
 * 地址编辑采用「一次只改一个槽位、保存即探测」：三个自动槽位和手动锁定都在
 * [saveAddress] 里原子落盘，不再边打字边写配置，也就没有「改了忘了存」的状态。
 */
@HiltViewModel
class SettingsViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val contextRepository: ContextRepository,
    private val chatRepository: ChatRepository,
    private val appPreferences: AppPreferences,
    private val apiService: AvelineApiService,
    private val webSocketManager: WebSocketManager,
    private val endpointResolver: EndpointResolver,
    private val dataSyncManager: DataSyncManager
) : ViewModel() {

    private val _uiState = MutableStateFlow(SettingsUiState())
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    /** 保存地址后的重探任务；连续保存时只保留最后一次，避免探测器排队。 */
    private var addressReprobeJob: Job? = null

    init {
        loadSettings()
        observeActiveEndpoint()
        refreshCandidates()
    }

    /** 跟随裁决器展示「当前生效地址 / 通道」：通道会随网络变化自动切换，不能只读一次快照。 */
    private fun observeActiveEndpoint() {
        viewModelScope.launch {
            endpointResolver.active.collect {
                val endpoint = displayEndpoint()
                _uiState.update { state -> state.withEndpoint(endpoint) }
            }
        }
    }

    /**
     * 界面展示用的「当前生效地址 / 通道」。
     *
     * 手动锁定非空时它**就是**生效地址，与裁决器上一次裁决无关；否则沿用裁决器结果。
     * 手动锁定刻意不探测，所以没有「可达 / 不可达」结论，按无已知问题展示。
     */
    private fun displayEndpoint(): ResolvedEndpoint {
        val manual = appPreferences.backendUrl.trim()
        if (manual.isEmpty()) return endpointResolver.active.value
        return ResolvedEndpoint(manual, EndpointChannel.MANUAL, reachable = true)
    }

    private fun channelLabel(channel: EndpointChannel): String = when (channel) {
        EndpointChannel.MANUAL -> "手动锁定"
        EndpointChannel.LAN -> "局域网"
        EndpointChannel.VPN -> "组网"
        EndpointChannel.TUNNEL -> "公网"
        EndpointChannel.NONE -> "未确定"
    }

    /** 把裁决结果与候选探测结果一起写进 UI 状态。 */
    private fun SettingsUiState.withEndpoint(
        endpoint: ResolvedEndpoint,
        probes: List<EndpointCandidateProbe> = candidateProbes
    ): SettingsUiState = copy(
        activeUrl = endpoint.url,
        activeChannel = channelLabel(endpoint.channel),
        activeReachable = endpoint.reachable,
        activeLatencyMs = probes.firstOrNull {
            it.reachable && sameAddress(it.url, endpoint.url)
        }?.latencyMs,
        candidateProbes = probes
    )

    private fun loadSettings() {
        viewModelScope.launch {
            val packageInfo: PackageInfo = try {
                context.packageManager.getPackageInfo(context.packageName, 0)
            } catch (e: PackageManager.NameNotFoundException) {
                PackageInfo().apply {
                    versionName = "1.0.0"
                    @Suppress("DEPRECATION")
                    versionCode = 1
                }
            }

            val buildVersion = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                packageInfo.longVersionCode.toString()
            } else {
                @Suppress("DEPRECATION")
                packageInfo.versionCode.toString()
            }

            _uiState.update { state ->
                state.copy(
                    hasUsageStatsPermission = contextRepository.hasUsageStatsPermission(),
                    hasNotificationPermission = contextRepository.hasNotificationListenerPermission(),
                    isContextSyncEnabled = appPreferences.isContextSyncEnabled,
                    backendUrl = appPreferences.backendUrl,
                    lanUrl = appPreferences.lanUrl,
                    vpnUrl = appPreferences.vpnUrl,
                    tunnelUrl = appPreferences.tunnelUrl,
                    accessToken = appPreferences.accessToken,
                    autoTtsEnabled = appPreferences.autoTtsEnabled,
                    stageDirectionEnabled = appPreferences.stageDirectionEnabled,
                    residentModeEnabled = appPreferences.residentModeEnabled,
                    appVersion = packageInfo.versionName ?: "1.0.0",
                    buildVersion = buildVersion
                ).withEndpoint(displayEndpoint())
            }
        }
    }

    /**
     * 只探测候选地址、不改生效地址，供网络页逐行展示每条通道的状态。
     *
     * @param force 为 true 时即使上一轮还在探测也重新发起（用户主动点「重新探测」）。
     */
    fun refreshCandidates(force: Boolean = false) {
        if (!force && _uiState.value.isProbingCandidates) return
        viewModelScope.launch {
            _uiState.update { it.copy(isProbingCandidates = true) }
            val probes = endpointResolver.probeCandidates()
            _uiState.update { state ->
                state.copy(isProbingCandidates = false)
                    .withEndpoint(displayEndpoint(), probes)
            }
        }
    }

    /**
     * 保存单个地址槽位并立刻探测。
     *
     * 空值合法（表示停用该通道）；格式错误直接忽略，输入面板会同步禁用保存按钮。
     */
    internal fun saveAddress(slot: SettingsAddressSlot, raw: String) {
        val value = raw.trim()
        if (isInvalidBackendUrl(value)) return

        when (slot) {
            SettingsAddressSlot.LAN -> appPreferences.lanUrl = value
            SettingsAddressSlot.VPN -> appPreferences.vpnUrl = value
            SettingsAddressSlot.TUNNEL -> appPreferences.tunnelUrl = value
            SettingsAddressSlot.MANUAL -> appPreferences.backendUrl = value
        }

        _uiState.update { state ->
            state.copy(
                lanUrl = if (slot == SettingsAddressSlot.LAN) value else state.lanUrl,
                vpnUrl = if (slot == SettingsAddressSlot.VPN) value else state.vpnUrl,
                tunnelUrl = if (slot == SettingsAddressSlot.TUNNEL) value else state.tunnelUrl,
                backendUrl = if (slot == SettingsAddressSlot.MANUAL) value else state.backendUrl,
                connectionTestResult = null
            )
        }
        probeAfterAddressChange()
    }

    /**
     * 地址落盘后跑一次完整裁决 + 候选探测。
     *
     * 缺了这一步，用户保存后状态卡会停在旧通道上（周期重探只在「有更优候选」时才跑）。
     */
    private fun probeAfterAddressChange() {
        addressReprobeJob?.cancel()
        addressReprobeJob = viewModelScope.launch {
            _uiState.update { it.copy(isReprobing = true, isProbingCandidates = true) }
            endpointResolver.resolve("设置页保存地址")
            val probes = endpointResolver.probeCandidates()
            _uiState.update { state ->
                state.copy(isReprobing = false, isProbingCandidates = false)
                    .withEndpoint(displayEndpoint(), probes)
            }
        }
    }

    /** 保存访问令牌；令牌参与探测鉴权，保存后立即重探候选。 */
    fun saveAccessToken(raw: String) {
        val token = raw.trim()
        appPreferences.accessToken = token
        _uiState.update { it.copy(accessToken = token, connectionTestResult = null) }
        refreshCandidates(force = true)
    }

    /**
     * 立即重新裁决一次通道并刷新候选结果。
     */
    fun reprobeEndpoint() {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isReprobing = true,
                    isProbingCandidates = true,
                    connectionTestResult = null
                )
            }
            val endpoint = endpointResolver.resolve("设置页手动重探")
            val probes = endpointResolver.probeCandidates()
            _uiState.update { state ->
                state.copy(
                    isReprobing = false,
                    isProbingCandidates = false,
                    connectionTestResult = if (endpoint != null) {
                        ConnectionTestResult(
                            success = true,
                            message = "已连接：${channelLabel(endpoint.channel)}"
                        )
                    } else {
                        ConnectionTestResult(
                            success = false,
                            message = if (hasConfiguredCandidate()) {
                                "所有候选地址都不可达，请检查地址、访问令牌与网络"
                            } else {
                                "还没有可用的候选地址，请先填写局域网、组网或公网域名"
                            }
                        )
                    }
                ).withEndpoint(displayEndpoint(), probes)
            }
            if (endpoint != null) webSocketManager.connect(forceReconnect = true)
        }
    }

    private fun hasConfiguredCandidate(): Boolean =
        appPreferences.lanUrl.isNotBlank() ||
            appPreferences.vpnUrl.isNotBlank() ||
            appPreferences.tunnelUrl.isNotBlank()

    fun testConnection() {
        viewModelScope.launch {
            _uiState.update { it.copy(isTestingConnection = true, connectionTestResult = null) }
            try {
                val response = apiService.healthCheck()
                _uiState.update {
                    it.copy(
                        isTestingConnection = false,
                        connectionTestResult = ConnectionTestResult(
                            success = response.isSuccessful,
                            message = if (response.isSuccessful) {
                                "连接成功"
                            } else {
                                "服务器返回错误：${response.code()}"
                            }
                        )
                    )
                }
            } catch (e: Exception) {
                _uiState.update {
                    it.copy(
                        isTestingConnection = false,
                        connectionTestResult = ConnectionTestResult(
                            success = false,
                            message = "连接失败：${e.message ?: "未知错误"}"
                        )
                    )
                }
            }
        }
    }

    fun refreshPermissions() {
        viewModelScope.launch {
            _uiState.update { state ->
                state.copy(
                    hasUsageStatsPermission = contextRepository.hasUsageStatsPermission(),
                    hasNotificationPermission = contextRepository.hasNotificationListenerPermission()
                )
            }
        }
    }

    fun toggleAutoTts(enabled: Boolean) {
        appPreferences.autoTtsEnabled = enabled
        _uiState.update { it.copy(autoTtsEnabled = enabled) }
    }

    /** 写入后聊天页订阅的 flow 会立即让已显示的消息重新分段。 */
    fun toggleStageDirection(enabled: Boolean) {
        appPreferences.stageDirectionEnabled = enabled
        _uiState.update { it.copy(stageDirectionEnabled = enabled) }
    }

    fun toggleResidentMode(enabled: Boolean) {
        appPreferences.residentModeEnabled = enabled
        if (enabled) {
            AvelineForegroundServiceV2.start(context)
            dataSyncManager.startPeriodicSync()
            if (!context.isIgnoringBatteryOptimizations()) {
                _uiState.update { it.copy(showBatteryOptimizationRequest = true) }
            }
        } else {
            AvelineForegroundServiceV2.stop(context)
            dataSyncManager.stopPeriodicSync()
        }
        _uiState.update { it.copy(residentModeEnabled = enabled) }
    }

    fun confirmBatteryOptimization() {
        _uiState.update { it.copy(showBatteryOptimizationRequest = false) }
        context.requestIgnoreBatteryOptimizations()
    }

    fun dismissBatteryOptimization() {
        _uiState.update { it.copy(showBatteryOptimizationRequest = false) }
    }

    fun openUsageStatsSettings() {
        contextRepository.openUsageStatsSettings()
    }

    fun openNotificationSettings() {
        contextRepository.openNotificationListenerSettings()
    }

    fun toggleContextSync(enabled: Boolean) {
        appPreferences.isContextSyncEnabled = enabled
        _uiState.update { it.copy(isContextSyncEnabled = enabled) }
    }

    fun showClearHistoryConfirm() {
        _uiState.update { it.copy(showClearConfirm = true) }
    }

    fun hideClearHistoryConfirm() {
        _uiState.update { it.copy(showClearConfirm = false) }
    }

    /**
     * 清除当前会话的聊天历史。没有 currentSessionId 时直接报错，避免静默失败。
     */
    fun clearHistory() {
        viewModelScope.launch {
            _uiState.update { it.copy(isClearing = true, clearError = null) }

            val sessionId = appPreferences.currentSessionId
            if (sessionId.isNullOrBlank()) {
                _uiState.update {
                    it.copy(
                        isClearing = false,
                        showClearConfirm = false,
                        clearError = "没有当前会话，无法清除"
                    )
                }
                return@launch
            }

            chatRepository.clearHistory(sessionId).fold(
                onSuccess = {
                    _uiState.update {
                        it.copy(isClearing = false, showClearConfirm = false, clearError = null)
                    }
                },
                onFailure = { e ->
                    _uiState.update {
                        it.copy(
                            isClearing = false,
                            showClearConfirm = false,
                            clearError = "清除失败：${e.message ?: "未知错误"}"
                        )
                    }
                }
            )
        }
    }

    fun clearClearError() {
        _uiState.update { it.copy(clearError = null) }
    }
}
