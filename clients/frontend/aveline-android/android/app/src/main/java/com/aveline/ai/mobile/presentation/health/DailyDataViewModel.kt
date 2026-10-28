package com.aveline.ai.mobile.presentation.health

import android.app.Activity
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.samsung.SamsungHealthReader
import com.aveline.ai.mobile.data.samsung.SamsungHealthSnapshot
import com.aveline.ai.mobile.data.samsung.toSyncJson
import com.aveline.ai.mobile.data.wear.WearDataSource
import com.aveline.ai.mobile.domain.models.BatteryStatus
import com.aveline.ai.mobile.domain.models.HealthData
import com.aveline.ai.mobile.domain.models.NetworkType
import com.aveline.ai.mobile.domain.repository.ContextRepository
import com.aveline.ai.mobile.domain.repository.HealthRepository
import com.aveline.ai.mobile.presentation.health.daily.DailyDataUiState
import com.aveline.ai.mobile.presentation.health.daily.DailyTab
import com.aveline.ai.mobile.presentation.health.daily.loadAiNutritionEntries
import com.aveline.ai.mobile.presentation.health.daily.mergeInto
import com.aveline.ai.mobile.presentation.health.daily.parseDailyPortrait
import com.aveline.ai.mobile.presentation.health.daily.string
import com.aveline.ai.mobile.services.health.StartupHealthSyncManager
import dagger.hilt.android.lifecycle.HiltViewModel
import java.time.Instant
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Life（生活）页的数据源。
 *
 * 三星健康这条链路的关键点：**启动同步读到的快照必须被 Life 页复用**。
 * 以前启动同步读完就把快照丢掉，Life 页只能自己再读一遍全量 SDK（几十个查询，
 * 要好几秒），用户看到的"生活页面卡几秒"就是这么来的。
 * 现在快照留在 [StartupHealthSyncManager.cache] 里，本 ViewModel 订阅它，
 * 进页面即可直接渲染；只有数据确实过期时才重新读 SDK。
 */
@HiltViewModel
class DailyDataViewModel @Inject constructor(
    private val healthRepository: HealthRepository,
    private val contextRepository: ContextRepository,
    private val wearDataSource: WearDataSource,
    private val samsungHealthReader: SamsungHealthReader,
    private val startupHealthSyncManager: StartupHealthSyncManager
) : ViewModel() {
    // lastRefreshTime 只表示"三星健康数据上次同步时间"：
    // App 启动同步成功后带过来，避免进 Life 页又立刻重复读一次 SDK。
    private val _uiState = MutableStateFlow(
        DailyDataUiState(lastRefreshTime = startupHealthSyncManager.lastSyncAt)
    )
    val uiState: StateFlow<DailyDataUiState> = _uiState.asStateFlow()

    // Samsung Health 同步防重入标志(独立于 isLoading)。
    // 不能用 _uiState.isLoading 做守卫: refreshData() 也会置 isLoading=true,
    // 会导致 ON_RESUME/进页时 Samsung 同步被误判为"正在加载"而跳过, 健康数据不刷新。
    private var isSyncingSamsungHealth = false

    init {
        collectWearHealthData()
        observeStartupHealthCache()
        refreshData()
    }

    /**
     * 订阅启动同步产出的快照。
     *
     * 启动同步在后台跑，Life 页可能在它完成之前就被打开；
     * 订阅之后快照一到就直接渲染，不必等用户手动刷新，也不必再读一次 SDK。
     */
    private fun observeStartupHealthCache() {
        viewModelScope.launch {
            startupHealthSyncManager.cache.collect { cache ->
                if (cache == null) return@collect
                applySnapshot(cache.snapshot, cache.readAt)
                // 启动同步已经上报过就别再报一次；上报失败的那份需要补报。
                if (!cache.reported) syncSamsungHealthToBackend(cache.snapshot)
            }
        }
    }

    /**
     * 持续监听手表通过 Wearable Data Layer 发送的健康数据。
     *
     * 收到数据后更新 UI 状态,并尝试同步到后端。与 Health Connect 数据独立,
     * 后续可再合并优先级策略。
     */
    private fun collectWearHealthData() {
        viewModelScope.launch {
            runCatching {
                wearDataSource.observeHealthData().collect { data ->
                    _uiState.update {
                        it.copy(
                            steps = data.steps.takeIf { s -> s > 0 } ?: it.steps,
                            heartRate = data.heartRate ?: it.heartRate,
                            heartRateTimestamp = data.heartRateTimestamp?.toEpochMilli()
                                ?: it.heartRateTimestamp,
                            healthWeightKg = data.weight ?: it.healthWeightKg,
                            heightM = data.height ?: it.heightM,
                            bodyFatPercent = data.bodyFat ?: it.bodyFatPercent,
                            sleepMinutes = data.sleepMinutes ?: it.sleepMinutes,
                            sleepStartTime = data.sleepStartTime?.toEpochMilli()
                                ?: it.sleepStartTime,
                            sleepEndTime = data.sleepEndTime?.toEpochMilli()
                                ?: it.sleepEndTime,
                            bloodPressureSystolic = data.bloodPressureSystolic
                                ?: it.bloodPressureSystolic,
                            bloodPressureDiastolic = data.bloodPressureDiastolic
                                ?: it.bloodPressureDiastolic,
                            bodyTemperature = data.bodyTemperature ?: it.bodyTemperature,
                            bloodGlucose = data.bloodGlucose ?: it.bloodGlucose
                            // 不更新 lastRefreshTime：它只代表三星健康同步时间，
                            // 手表持续推数据会把三星同步的 30 秒节流永久卡住。
                        )
                    }
                    syncWearHealthDataToBackend(data)
                }
            }.onFailure { e ->
                // Wearable API 不可用或其他异常,不崩溃 app,只记录日志
                android.util.Log.w("DailyDataViewModel", "手表数据监听失败: ${e.message}")
            }
        }
    }

    private fun syncWearHealthDataToBackend(data: HealthData) {
        viewModelScope.launch {
            runCatching {
                healthRepository.syncHealthData(
                    buildJsonObject {
                        put("source", "wear_os")
                        // 实时数据 (Health Services)
                        put("steps", data.steps.takeIf { it > 0 })
                        put("heart_rate", data.heartRate)
                        put("heart_rate_timestamp", data.heartRateTimestamp?.toString())
                        // 历史数据 (Health Connect, 纯 IO 读取)
                        put("weight_kg", data.weight)
                        put("weight_timestamp", data.weightTimestamp?.toString())
                        put("height_m", data.height)
                        put("height_timestamp", data.heightTimestamp?.toString())
                        put("body_fat_percent", data.bodyFat)
                        put("sleep_minutes", data.sleepMinutes)
                        put("sleep_start_time", data.sleepStartTime?.toString())
                        put("sleep_end_time", data.sleepEndTime?.toString())
                        put("blood_pressure_systolic", data.bloodPressureSystolic)
                        put("blood_pressure_diastolic", data.bloodPressureDiastolic)
                        put("body_temperature", data.bodyTemperature)
                        put("blood_glucose", data.bloodGlucose)
                        put("collected_at", Instant.now().toString())
                    }
                )
            }
        }
    }

    /**
     * 从 Samsung Health 读取健康数据并同步到后端。
     *
     * 国行设备 Health Connect 不可用,改用 Samsung Health Data SDK 直接读取
     * Samsung Health 应用的数据存储。需要 Activity 来请求权限。
     *
     * 数据流: Samsung Health (手机应用) → SamsungHealthReader → UI + 后端
     *
     * @param activity 用于显示 Samsung Health 权限请求 UI 的 Activity
     * @param force 手动刷新时传 true，跳过节流与缓存复用
     */
    fun syncFromSamsungHealth(activity: Activity, force: Boolean = false) {
        // 防重入: 正在同步时跳过(定时器可能在同步进行中触发)。
        // 用独立标志而非 isLoading, 避免与 refreshData() 互相阻塞。
        if (isSyncingSamsungHealth) return
        isSyncingSamsungHealth = true
        viewModelScope.launch {
            try {
                // 步骤 1: 能复用就不读 SDK。
                // 1a) 启动同步还在跑 → 等它跑完，直接用它的结果（并发读 SDK 只会更慢）。
                if (!force && startupHealthSyncManager.isSyncing) {
                    val pending = startupHealthSyncManager.awaitStartupSync(STARTUP_SYNC_WAIT_MS)
                    if (pending != null) {
                        applySnapshot(pending.snapshot, pending.readAt)
                        return@launch
                    }
                }
                // 1b) 已有新鲜快照 → 直接渲染，不读 SDK、不重复上报。
                if (!force) {
                    val cache = startupHealthSyncManager.cache.value
                    if (cache != null &&
                        System.currentTimeMillis() - cache.readAt < MIN_SYNC_INTERVAL_MS
                    ) {
                        applySnapshot(cache.snapshot, cache.readAt)
                        return@launch
                    }
                    // 状态里已经有刚同步过的数据（快照已被别处消费掉）时也不用再读。
                    val lastRefresh = _uiState.value.lastRefreshTime
                    if (lastRefresh > 0L &&
                        System.currentTimeMillis() - lastRefresh < MIN_SYNC_INTERVAL_MS
                    ) {
                        return@launch
                    }
                }

                // 自动同步不再往 Life 页塞过程提示（"正在同步..."）：页面上已没有手动刷新入口，
                // 过程提示只会让「今日健康」等栏目上下跳动。
                _uiState.update {
                    it.copy(
                        isLoading = true,
                        message = null,
                        error = null
                    )
                }

                // 步骤 2: 请求权限（已授权时不再在主线程逐项查权限）
                val granted = runCatching {
                    samsungHealthReader.ensurePermissions(activity)
                }.getOrDefault(false)

                if (!granted) {
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            message = "需要授权才能读取三星健康数据,请在 Samsung Health 中开启权限"
                        )
                    }
                    return@launch
                }

                // 步骤 3: 读取数据（与 App 启动同步共用一把锁，避免并发读 SDK）
                val snapshot = runCatching {
                    startupHealthSyncManager.withSamsungLock { samsungHealthReader.readAll() }
                }.getOrElse { e ->
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            error = "读取数据失败: ${e.message}"
                        )
                    }
                    return@launch
                }

                // 步骤 4: 更新 UI 状态
                applySnapshot(snapshot, System.currentTimeMillis())
                _uiState.update { it.copy(isLoading = false) }

                // 步骤 5: 同步到后端（这份数据是本次新读的，必须上报）
                syncSamsungHealthToBackend(snapshot)
                startupHealthSyncManager.markSynced(snapshot)
            } finally {
                isSyncingSamsungHealth = false
            }
        }
    }

    /** 把一份三星健康快照合并进 UI 状态。 */
    private fun applySnapshot(snapshot: SamsungHealthSnapshot, readAt: Long) {
        _uiState.update { state ->
            snapshot.mergeInto(state).copy(lastRefreshTime = readAt)
        }
    }

    /**
     * 将 Samsung Health 快照同步到后端。
     */
    private fun syncSamsungHealthToBackend(snapshot: SamsungHealthSnapshot) {
        viewModelScope.launch {
            runCatching {
                healthRepository.syncHealthData(snapshot.toSyncJson())
            }
            refreshAiNutritionEntries()
        }
    }

    private suspend fun refreshAiNutritionEntries() {
        val aiEntries = loadAiNutritionEntries(healthRepository) ?: return
        _uiState.update { state ->
            state.copy(
                nutritionEntries = state.nutritionEntries.filterNot {
                    it.source.startsWith("ai_photo")
                } + aiEntries
            )
        }
    }

    fun setActiveTab(tab: DailyTab) {
        _uiState.update { it.copy(activeTab = tab) }
    }

    fun refreshData() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }

            runCatching {
                val portrait = healthRepository.getDailyPortraitToday().getOrThrow()
                val recent = healthRepository.getDailyRecent(limit = 12).getOrThrow()
                val parsed = parseDailyPortrait(portrait, recent)

                // 设备上下文: 电池/网络/亮度/音量 (本地系统 API, 不需要 HC 权限)
                // 单独 try, 失败不阻断主流程 (设备上下文是次要信息)
                val deviceCtx = runCatching { contextRepository.getDeviceContext() }.getOrNull()
                val aiNutritionEntries = loadAiNutritionEntries(
                    healthRepository,
                    parsed.portraitDate.ifBlank { null }
                )

                _uiState.update {
                    it.copy(
                        isLoading = false,
                        portraitDate = parsed.portraitDate,
                        wakeup = parsed.wakeup,
                        sleep = parsed.sleep,
                        drinkTotalMl = parsed.drinkTotalMl,
                        drinkCount = parsed.drinkCount,
                        studyTotalMinutes = parsed.studyTotalMinutes,
                        studyCount = parsed.studyCount,
                        studySessions = parsed.studySessions,
                        meals = parsed.meals,
                        nutritionEntries = aiNutritionEntries?.let { aiEntries ->
                            it.nutritionEntries.filterNot { entry ->
                                entry.source.startsWith("ai_photo")
                            } + aiEntries
                        } ?: it.nutritionEntries,
                        reducedModeActive = parsed.reducedModeActive,
                        reducedModeReason = parsed.reducedModeReason,
                        reducedModeExpectedEndTs = parsed.reducedModeExpectedEndTs,
                        weightKg = parsed.weightKg,
                        recentFiles = parsed.recentFiles,
                        batteryLevel = deviceCtx?.batteryLevel,
                        isCharging = deviceCtx?.isCharging ?: false,
                        batteryStatus = deviceCtx?.batteryStatus ?: BatteryStatus.UNKNOWN,
                        networkType = deviceCtx?.networkType ?: NetworkType.UNKNOWN,
                        screenBrightness = deviceCtx?.screenBrightness,
                        volumeLevel = deviceCtx?.volumeLevel,
                        // 健康指标(心率/睡眠/体脂/身高/BMI 等)不再由 refreshData 触碰,
                        // 全部由三星健康快照填充并保留, 避免 HC 的 null 覆盖。
                        // lastRefreshTime 也不在这里更新: 它只代表三星健康同步时间,
                        // 否则进 Life 页时会被误判成"刚同步过"而跳过。
                        error = null
                    )
                }
            }.onFailure { error ->
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        error = error.message ?: "加载 Daily Data 失败"
                    )
                }
            }
        }
    }

    /**
     * 记录喝水。
     *
     * 修复 P0-9: 原实现按 units(250ml/单位)上报,UI 的 200/300/500ml 按钮做 ml/250 转换时
     * 200ml→0→coerceAtLeast(1)=1→后端记 250ml(多记 50ml),300ml→1→后端记 250ml(少记 50ml)。
     * 后端 /v1/context/drink 实际支持 amount_ml 字段(优先于 units),改为直接传毫升数,
     * 200ml→200ml, 300ml→300ml, 500ml→500ml,精确无误。
     *
     * @param amountMl 实际喝水量(毫升),后端会 clamp 到 [50, 5000]
     */
    fun recordDrink(amountMl: Int = 250) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, message = null, error = null) }
            healthRepository.recordDailyDrink(
                buildJsonObject {
                    put("amount_ml", amountMl)
                }
            ).onSuccess { response ->
                _uiState.update {
                    it.copy(message = response.string("message").ifBlank { "已记录喝水" })
                }
                refreshData()
            }.onFailure { error ->
                _uiState.update {
                    it.copy(isLoading = false, error = error.message ?: "记录喝水失败")
                }
            }
        }
    }

    fun startStudy(subject: String, durationMinutes: Int, note: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, message = null, error = null) }
            healthRepository.recordDailyStudy(
                buildJsonObject {
                    put("subject", subject)
                    put("duration_minutes", durationMinutes)
                    if (note.isNotBlank()) {
                        put("note", note)
                    }
                    put("enter_low_disturbance", true)
                    put("switch_mode_to_study", true)
                }
            ).onSuccess { response ->
                _uiState.update {
                    it.copy(message = response.string("message").ifBlank { "学习会话已开始" })
                }
                refreshData()
            }.onFailure { error ->
                _uiState.update {
                    it.copy(isLoading = false, error = error.message ?: "开始学习失败")
                }
            }
        }
    }

    fun finishStudy() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, message = null, error = null) }
            healthRepository.finishDailyStudy().onSuccess { response ->
                _uiState.update {
                    it.copy(message = response.string("message").ifBlank { "学习会话已结束" })
                }
                refreshData()
            }.onFailure { error ->
                _uiState.update {
                    it.copy(isLoading = false, error = error.message ?: "结束学习失败")
                }
            }
        }
    }

    fun clearError() {
        _uiState.update { it.copy(error = null, message = null) }
    }

    private companion object {
        /** 自动同步的最小间隔（毫秒） */
        private const val MIN_SYNC_INTERVAL_MS = 30_000L
        /** 等启动同步结束的最长时间（毫秒）；超时后自己再读 SDK。 */
        private const val STARTUP_SYNC_WAIT_MS = 15_000L
    }
}
