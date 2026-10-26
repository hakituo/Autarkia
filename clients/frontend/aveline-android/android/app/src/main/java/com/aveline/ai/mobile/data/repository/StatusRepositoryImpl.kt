package com.aveline.ai.mobile.data.repository

import android.util.Log
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.data.remote.api.WebSocketMessage
import com.aveline.ai.mobile.domain.models.Emotion
import com.aveline.ai.mobile.domain.models.LifeStatus
import com.aveline.ai.mobile.domain.repository.StatusRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.filterIsInstance
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.time.Instant
import java.time.ZoneId
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class StatusRepositoryImpl @Inject constructor(
    private val apiService: AvelineApiService,
    private val webSocketManager: WebSocketManager
) : StatusRepository {

    private val scope = CoroutineScope(Dispatchers.IO)

    private val _cachedLifeStatus = MutableStateFlow<LifeStatus?>(null)
    val cachedLifeStatus: StateFlow<LifeStatus?> = _cachedLifeStatus.asStateFlow()

    /**
     * HTTP 回源时钟：只有真正成功拉到 `/life/status` 才推进。
     *
     * 曾经 WS 推送也写这个字段，而后端每秒广播一次 `life_status`，导致
     * `now - lastApiFetchTime` 永远小于 60 秒缓存窗口：接口再也不回源，
     * `dailyPlan`（含 execution_status）整晚停在最后一次拉取的快照上，
     * 凌晨会看到「昨天下午的日程正在进行」。
     */
    private var lastApiFetchTime: Long = 0
    private var lastWsUpdateTime: Long = 0

    /** 最近一次因 WS 提示（跨日/活动变化）触发补拉的时间，用于限流。 */
    private var lastPlanRefetchTime: Long = 0
    private var _cachedPersona: String? = null

    /**
     * 最近一次成功拉取日程时的**设备**日期（YYYY-MM-DD）。
     *
     * 不能拿 `daily_plan.date` 与设备日期直接比：后端按配置时区（默认
     * Asia/Shanghai）生成计划，设备时区可能不同（出国、手动改时区、服务器
     * 不在同一时区），两边日期天然会差一天，那样每天都会被误判成「跨日过期」，
     * 缓存形同失效、WS 每 30 秒就补拉一次。
     *
     * 这里只关心「设备自己的自然日有没有翻页」：以最近一次成功拉取时的设备
     * 日期为锚点，当前设备日期严格晚于它才算过期。
     */
    private var planDeviceDate: String = ""

    /** 可替换时钟，仅用于单元测试固定「现在」。 */
    internal var clock: () -> Long = System::currentTimeMillis

    companion object {
        private const val TAG = "StatusRepositoryImpl"
        private const val FALLBACK_API_INTERVAL_MS = 60_000L
        private const val WS_THROTTLE_INTERVAL_MS = 5_000L
        private const val SIGNIFICANT_CHANGE_THRESHOLD = 0.05f

        /** WS 触发回源补拉日程的最小间隔，避免推送风暴把接口打满。 */
        internal const val PLAN_REFETCH_MIN_INTERVAL_MS = 30_000L
    }

    init {
        observeLifeStatusFromWebSocket()
    }

    private fun observeLifeStatusFromWebSocket() {
        scope.launch {
            webSocketManager.messages.collect { message ->
                when (message) {
                    is WebSocketMessage.LifeStatusUpdate -> {
                        if (applyLifeStatusUpdate(message)) {
                            maybeRefetchLifeStatus("ws_life_status")
                        }
                    }
                    is WebSocketMessage.ReconnectSync -> {
                        if (applyReconnectSync(message)) {
                            maybeRefetchLifeStatus("ws_reconnect_sync")
                        }
                    }
                    else -> Unit
                }
            }
        }
    }

    /**
     * 应用一条 WS 生命状态推送。
     *
     * WS 只推生命值（energy/hunger/…）与 activity，**不携带 daily_plan 与槽位的
     * execution_status**，所以这里只更新对应字段、沿用缓存里的日程，
     * 绝不推进 [lastApiFetchTime]——否则 60 秒缓存窗口被每秒推送永久续命，
     * 接口不再回源，日程会整晚停在旧快照上。
     *
     * @return true 表示缓存里的日程已过时（跨日/当前活动变了），需要回源补拉。
     */
    internal fun applyLifeStatusUpdate(message: WebSocketMessage.LifeStatusUpdate): Boolean {
        val now = clock()
        val current = _cachedLifeStatus.value

        // WS 推的 activity 比缓存更权威（活动切换由后端 tick 决定）。旧实现忽略了
        // message.activity，导致状态页的「当前活动」和日程一样被冻结。
        val nextActivity = message.activity.ifBlank { current?.activity ?: "idle" }
        val newStatus = LifeStatus(
            health = message.life["energy"] ?: 0.5f,
            hunger = message.life["hunger"] ?: 0.5f,
            happiness = message.life["mood_score"] ?: 0.5f,
            energy = message.life["energy"] ?: 0.5f,
            timestamp = message.timestamp,
            scope = current?.scope,
            activity = nextActivity,
            activityChatEligible = current?.activityChatEligible ?: true,
            replyMode = current?.replyMode ?: "immediate",
            replyDelayMinSeconds = current?.replyDelayMinSeconds,
            replyDelayMaxSeconds = current?.replyDelayMaxSeconds,
            isSleeping = current?.isSleeping ?: false,
            sleepPhase = current?.sleepPhase,
            dailyPlan = current?.dailyPlan
        )

        val hasSignificantChange = current == null ||
            kotlin.math.abs(current.health - newStatus.health) > SIGNIFICANT_CHANGE_THRESHOLD ||
            kotlin.math.abs(current.hunger - newStatus.hunger) > SIGNIFICANT_CHANGE_THRESHOLD ||
            kotlin.math.abs(current.happiness - newStatus.happiness) > SIGNIFICANT_CHANGE_THRESHOLD ||
            kotlin.math.abs(current.energy - newStatus.energy) > SIGNIFICANT_CHANGE_THRESHOLD

        if (hasSignificantChange || now - lastWsUpdateTime >= WS_THROTTLE_INTERVAL_MS) {
            _cachedLifeStatus.value = newStatus
            lastWsUpdateTime = now
        }

        val activityChanged = current != null &&
            message.activity.isNotBlank() &&
            message.activity != current.activity
        return activityChanged || isCachedPlanStaleForDeviceDay()
    }

    /**
     * 应用重连同步帧；语义与 [applyLifeStatusUpdate] 一致：不推进接口回源时钟。
     *
     * @return true 表示需要回源补拉日程。
     */
    internal fun applyReconnectSync(message: WebSocketMessage.ReconnectSync): Boolean {
        val lifeMap = message.lifeStatus ?: return false
        val current = _cachedLifeStatus.value
        val status = LifeStatus(
            health = lifeMap["health"] ?: 0.5f,
            hunger = lifeMap["hunger"] ?: 0.5f,
            happiness = lifeMap["happiness"] ?: 0.5f,
            energy = lifeMap["energy"] ?: 0.5f,
            timestamp = clock(),
            scope = current?.scope,
            activity = current?.activity ?: "idle",
            activityChatEligible = current?.activityChatEligible ?: true,
            replyMode = current?.replyMode ?: "immediate",
            replyDelayMinSeconds = current?.replyDelayMinSeconds,
            replyDelayMaxSeconds = current?.replyDelayMaxSeconds,
            isSleeping = current?.isSleeping ?: false,
            sleepPhase = current?.sleepPhase,
            dailyPlan = current?.dailyPlan
        )
        _cachedLifeStatus.value = status
        lastWsUpdateTime = clock()
        return isCachedPlanStaleForDeviceDay()
    }

    /**
     * WS 提示日程过时后补拉一次接口（限流）。
     *
     * 放在独立协程里跑，避免 `/life/status` 的网络等待阻塞每秒一条的 WS 收集。
     */
    private fun maybeRefetchLifeStatus(reason: String) {
        val now = clock()
        if (now - lastPlanRefetchTime < PLAN_REFETCH_MIN_INTERVAL_MS) return
        lastPlanRefetchTime = now
        val persona = _cachedPersona
        scope.launch {
            Log.d(TAG, "WS 提示日程过时，回源补拉: $reason")
            forceRefreshLifeStatus(persona)
        }
    }

    /**
     * 缓存的日程是否已经跨过设备自然日。
     *
     * 只与 [planDeviceDate]（上次成功拉取时的设备日期）比较，不碰后端下发的
     * `daily_plan.date`，避免两端时区不同把计划误判成过期。
     */
    internal fun isCachedPlanStaleForDeviceDay(): Boolean =
        isDeviceDateAdvanced(planDeviceDate, deviceDateString())

    private fun deviceDateString(): String = deviceDateOf(clock())

    private fun deviceDateOf(epochMillis: Long): String =
        Instant.ofEpochMilli(epochMillis).atZone(ZoneId.systemDefault()).toLocalDate().toString()

    override suspend fun getLifeStatus(persona: String?): Result<LifeStatus> {
        val currentTime = clock()

        _cachedLifeStatus.value?.let { cached ->
            // 缓存只能服务于创建它的同一个 persona。旧判断只比较 cached.scope 与
            // _cachedPersona，没有比较“这次请求的 persona”，切角色后仍可能命中上一个角色缓存。
            // 另外设备跨日后必须回源：缓存里的 daily_plan / execution_status 都是昨天的。
            if (
                currentTime - lastApiFetchTime < FALLBACK_API_INTERVAL_MS &&
                persona == _cachedPersona &&
                cached.scope == persona &&
                !isCachedPlanStaleForDeviceDay()
            ) {
                return Result.success(cached)
            }
        }

        return try {
            val lifeStatus = apiService.getLifeStatus(persona = persona)
                .toLifeStatus(persona, currentTime)

            _cachedLifeStatus.value = lifeStatus
            _cachedPersona = persona
            lastApiFetchTime = currentTime
            planDeviceDate = deviceDateOf(currentTime)

            Result.success(lifeStatus)
        } catch (e: Exception) {
            Log.e(TAG, "从API获取生命状态失败", e)

            _cachedLifeStatus.value?.let { cached ->
                return Result.success(cached)
            }

            Result.failure(e)
        }
    }

    override fun observeEmotion(): Flow<Emotion> {
        return webSocketManager.messages
            .filterIsInstance<WebSocketMessage.EmotionUpdate>()
            .map { emotionUpdate ->
                Emotion(
                    primary = emotionUpdate.primary,
                    intensity = emotionUpdate.intensity,
                    colors = emotionUpdate.colors
                )
            }
    }

    override suspend fun wakeCompanion(
        persona: String?,
        conversationId: String?
    ): Result<String> = runControlRequest("唤醒") {
        apiService.wakeCompanion(controlPayload(persona, conversationId, "Android 状态面板立即唤醒"))
    }

    override suspend fun interruptCompanion(
        persona: String?,
        conversationId: String?
    ): Result<String> = runControlRequest("打断") {
        apiService.interruptCompanion(controlPayload(persona, conversationId, "Android 状态面板打断活动"))
    }

    override suspend fun skipCompanionActivity(
        persona: String?,
        conversationId: String?
    ): Result<String> = runControlRequest("跳过") {
        apiService.skipCompanionActivity(controlPayload(persona, conversationId, "Android 状态面板跳过活动"))
    }

    private fun controlPayload(
        persona: String?,
        conversationId: String?,
        message: String
    ): JsonObject = buildJsonObject {
        put("profile_filename", persona.orEmpty())
        put("conversation_id", conversationId.orEmpty())
        put("message", message)
    }

    private suspend fun runControlRequest(
        label: String,
        request: suspend () -> JsonObject
    ): Result<String> = try {
        val response = request()
        val backendMessage = response["message"]?.jsonPrimitive?.contentOrNull
        val status = response["status"]?.jsonPrimitive?.contentOrNull
        if (status != null && status != "success") {
            throw IllegalStateException(backendMessage ?: "$label 操作失败")
        }
        val action = response["action"]?.jsonPrimitive?.contentOrNull
        val message = when (action) {
            "woken_up" -> "已经唤醒，现在可以继续聊了。"
            "already_awake" -> "现在没有在睡觉。"
            "interrupted" -> "已经打断当前活动，接下来会优先回复你。"
            "already_available" -> "当前本来就可以直接聊天。"
            "already_skipped" -> "当前活动已经处于跳过状态。"
            "skipped", "auto_skipped" -> "已经跳过当前活动，不会再提醒返回。"
            "sleeping_use_wake" -> "当前仍在睡眠状态，请先唤醒。"
            else -> backendMessage ?: "$label 操作已完成。"
        }
        lastApiFetchTime = 0
        Result.success(message)
    } catch (e: Exception) {
        Log.e(TAG, "$label 角色状态失败", e)
        Result.failure(e)
    }

    fun observeLifeStatus(): StateFlow<LifeStatus?> {
        return cachedLifeStatus
    }

    suspend fun forceRefreshLifeStatus(persona: String? = null): Result<LifeStatus> {
        lastApiFetchTime = 0
        return getLifeStatus(persona)
    }

    fun clearCache() {
        _cachedLifeStatus.value = null
        _cachedPersona = null
        lastApiFetchTime = 0
        lastWsUpdateTime = 0
        lastPlanRefetchTime = 0
        planDeviceDate = ""
    }

    override suspend fun detectEmotion(text: String): Result<JsonObject> {
        return try {
            val payload = buildJsonObject { put("text", text) }
            Result.success(apiService.detectEmotion(payload))
        } catch (e: Exception) {
            Log.e(TAG, "检测情绪失败", e)
            Result.failure(e)
        }
    }

    override suspend fun getActiveCareStatus(): Result<JsonObject> {
        return try {
            Result.success(apiService.getActiveCareStatus())
        } catch (e: Exception) {
            Log.e(TAG, "获取主动关怀状态失败", e)
            Result.failure(e)
        }
    }

    override suspend fun triggerActiveCareCheck(): Result<JsonObject> {
        return try {
            Result.success(apiService.triggerActiveCareCheck())
        } catch (e: Exception) {
            Log.e(TAG, "触发主动关怀检查失败", e)
            Result.failure(e)
        }
    }
}

/**
 * 设备自然日是否已经推进到 [baseline] 之后（ISO 日期可直接按字典序比较）。
 *
 * - [baseline] 为空（还没成功拉过计划）→ false，交给 60 秒接口缓存窗口控制回源；
 * - 设备日期与锚点同日 → false，即使后端计划日期因时区不同差一天也不算过期；
 * - 设备日期回拨（用户改时区往回走）→ false，避免反复回源。
 */
internal fun isDeviceDateAdvanced(baseline: String?, current: String): Boolean =
    !baseline.isNullOrBlank() && current > baseline
