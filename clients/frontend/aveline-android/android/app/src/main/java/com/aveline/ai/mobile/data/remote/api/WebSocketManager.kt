package com.aveline.ai.mobile.data.remote.api

import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.services.endpoint.EndpointResolver
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference
import kotlin.random.Random
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class WebSocketManager @Inject constructor(
    private val okHttpClient: OkHttpClient,
    private val appPreferences: AppPreferences,
    private val endpointResolver: EndpointResolver
) {
    enum class ConnectionState {
        DISCONNECTED,
        CONNECTING,
        CONNECTED
    }

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val _connectionState = MutableStateFlow(ConnectionState.DISCONNECTED)
    val connectionState = _connectionState.asStateFlow()

    private val _messages = MutableSharedFlow<WebSocketMessage>(extraBufferCapacity = 64)
    val messages = _messages.asSharedFlow()

    private val webSocketRef = AtomicReference<WebSocket?>(null)
    private val currentUrlRef = AtomicReference<String?>(null)
    private var reconnectJob: Job? = null
    private val reconnectAttempts = AtomicInteger(0)
    private val manualDisconnect = AtomicBoolean(false)
    private var heartbeatJob: Job? = null
    private var heartbeatIntervalSec = 15

    /** 最近一次收到入站帧的时间（onOpen / onMessage 刷新），用于入站静默检测。 */
    private val lastInboundAt = AtomicLong(0L)

    // 未连接期间发送的消息先进队列, 连接建立(onOpen)后再补发, 避免消息在 sendMessage 时被静默丢弃
    private val pendingMessages = LinkedBlockingQueue<String>()

    companion object {
        private const val TAG = "WebSocketManager"

        /**
         * 把后端 URL 的协议头标准化为 ws(s)://。
         *
         * 不能用 replaceFirst("^http", "ws")：Kotlin 的 String.replaceFirst(oldValue, newValue)
         * 是字面量匹配而非正则，"^http" 只会匹配字面的 5 个字符，不会匹配"以 http 开头"的字符串。
         * 旧实现正是因此把 "http://host" 错误拼成 "wss://http://host"，OkHttp 解析后 host 段
         * 被当成 "http"，真正的 "//host:port/api/v1/ws" 全部落入 path，baseUrlInterceptor
         * 只修正 host/port 不修正 path，最终服务端收到畸形 path 匹配不到 /api/v1/ws 路由，
         * 落入静态文件挂载点被拒（403）。这正是 WS 反复 403 的根因。
         *
         * 用 startsWith 显式分支替代，避免字面量匹配陷阱。internal 便于单元测试覆盖。
         */
        internal fun normalizeWsScheme(decoded: String): String = when {
            decoded.startsWith("https://") -> "wss://" + decoded.removePrefix("https://")
            decoded.startsWith("http://") -> "ws://" + decoded.removePrefix("http://")
            decoded.startsWith("wss://") || decoded.startsWith("ws://") -> decoded
            else -> {
                // 兜底：无协议头（如 "xxx.trycloudflare.com" 或协议相对写法 "//192.0.2.1:8000"），
                // 统一补 wss://，并去掉协议相对前缀 "//"，避免被 OkHttp 解析成 path。
                "wss://" + decoded.removePrefix("//").trimStart('/')
            }
        }
    }

    init {
        // 裁决器切换生效地址（网络变化 / 失败降级）后立刻用新地址重连。
        //
        // 必须 forceReconnect：connect() 在「URL 相同且已连接」时会直接 return，
        // 而这里可能正是切回同一地址的场景。
        // 用 launch 起子协程而不是直接调用：connect() 内部会 cancel(reconnectJob)，
        // 而触发切换的正是 reconnectJob 自己，直接调用会把自己取消掉。
        scope.launch {
            endpointResolver.changes.collect { url ->
                Log.i(TAG, "生效地址变化，强制重连 WebSocket: $url")
                reconnectAttempts.set(0)
                launch { connect(forceReconnect = true) }
            }
        }
    }

    fun connect(forceReconnect: Boolean = false) {
        // 读 effectiveBackendUrl（裁决结果）而不是 backendUrl（手动锁定槽位）：
        // 自动模式下 backendUrl 是空的，只有裁决后的 activeUrl 才是真地址。
        val backendUrl = appPreferences.effectiveBackendUrl
        if (backendUrl.isEmpty()) {
            _connectionState.value = ConnectionState.DISCONNECTED
            scope.launch {
                _messages.emit(WebSocketMessage.Error("请先在设置中配置后端地址"))
            }
            return
        }
        val wsUrl = buildWsUrl(backendUrl)
        if (wsUrl.isEmpty()) {
            _connectionState.value = ConnectionState.DISCONNECTED
            return
        }

        val currentWs = currentUrlRef.get()
        val currentState = _connectionState.value
        if (!forceReconnect && wsUrl == currentWs && currentState == ConnectionState.CONNECTED) return
        if (currentState == ConnectionState.CONNECTING) return

        manualDisconnect.set(false)
        reconnectJob?.cancel()

        // 重建连接前必须先关掉旧 socket（同 URL 的 forceReconnect 也要关）。
        // 旧实现只在 URL 变化时 close：回前台 / 设置页 / 地址确认都会留下一条
        // "没人用的"连接 —— 心跳只走 webSocketRef、onMessage 又被归属校验丢弃，
        // 服务端要等 60s 心跳超时才回收，期间同一用户会有 2~3 条并发连接；
        // 残留 socket 还会拖慢广播（每条 5s 发送超时）。
        val previous = webSocketRef.getAndSet(null)
        _connectionState.value = ConnectionState.CONNECTING
        if (previous != null) {
            val reason = if (currentWs != null && currentWs != wsUrl) "url_changed" else "reconnect"
            previous.close(1000, reason)
        }
        currentUrlRef.set(wsUrl)

        val request = try {
            Request.Builder().url(wsUrl).build()
        } catch (e: IllegalArgumentException) {
            // URL 非法（如 scheme 缺失、host 为空）时不应 crash 主线程，
            // 降级为断开并提示，由上层修正配置后重连。
            Log.e(TAG, "WebSocket URL 非法，无法连接: $wsUrl", e)
            _connectionState.value = ConnectionState.DISCONNECTED
            scope.launch {
                _messages.emit(WebSocketMessage.Error("后端地址格式不正确: $wsUrl"))
            }
            return
        }
        val listener = object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                // 归属校验: 若此 socket 已被新连接替换, 关掉它（不能只是 return，
                // 否则服务端会一直保留这条已建立的连接，形成单向僵尸连接）
                if (webSocket !== webSocketRef.get()) {
                    webSocket.close(1000, "superseded")
                    return
                }
                _connectionState.value = ConnectionState.CONNECTED
                lastInboundAt.set(System.currentTimeMillis())
                // 无论首连还是重连都启动心跳(用上次缓存间隔,默认30s)。
                // 重连场景下若后端只回 reconnect_sync 不重发 connection_established,
                // 心跳也能恢复,避免连接静默断开后无法探活。
                startHeartbeat(heartbeatIntervalSec)
                // 补发连接期间入队的消息, 避免丢失
                flushPendingMessages(webSocket)
                if (reconnectAttempts.get() > 0) {
                    sendReconnect()
                }
                reconnectAttempts.set(0)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                // 归属校验: 旧连接的回调直接忽略, 避免旧 socket 的数据污染新连接
                if (webSocket !== webSocketRef.get()) return
                lastInboundAt.set(System.currentTimeMillis())
                scope.launch {
                    // 传入收到消息的 socket：服务端 ping 必须由同一条连接回 pong，
                    // 回错连接会让那条连接永远收不到 pong，被服务端 60s 心跳超时踢掉
                    _messages.emit(parseMessage(text, webSocket))
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                // 归属校验: 只有"当前正在用的"连接失败才需要处理; 被丢弃的旧连接回调一律忽略
                if (webSocket !== webSocketRef.get()) return
                Log.w(TAG, "WebSocket连接失败: ${t.message}")
                stopHeartbeat()
                _connectionState.value = ConnectionState.DISCONNECTED
                scope.launch {
                    _messages.emit(WebSocketMessage.Error(t.message ?: "连接失败"))
                }
                scheduleReconnect()
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                // 归属校验
                if (webSocket !== webSocketRef.get()) return
                stopHeartbeat()
                _connectionState.value = ConnectionState.DISCONNECTED
                if (!manualDisconnect.get()) {
                    scheduleReconnect()
                }
            }
        }

        val ws = okHttpClient.newWebSocket(request, listener)
        webSocketRef.set(ws)
    }

    /**
     * 补发连接建立期间入队的消息。
     * 逐个取出并发送; 某条发送失败(send 返回 false 说明 socket 已不可用)则放回队尾,
     * 等下次重连 onOpen 再补发, 由上层决定是否丢弃。
     */
    private fun flushPendingMessages(ws: WebSocket) {
        while (true) {
            val msg = pendingMessages.poll() ?: break
            try {
                if (!ws.send(msg)) {
                    pendingMessages.offer(msg)
                    break
                }
            } catch (e: Exception) {
                Log.w(TAG, "补发消息失败: ${e.message}")
                pendingMessages.offer(msg)
                break
            }
        }
    }

    fun disconnect() {
        manualDisconnect.set(true)
        stopHeartbeat()
        reconnectJob?.cancel()
        reconnectJob = null
        webSocketRef.getAndSet(null)?.close(1000, "client_disconnect")
        currentUrlRef.set(null)
        _connectionState.value = ConnectionState.DISCONNECTED
        // 手动断开时清空积压消息, 避免重连后补发旧消息(用户已主动终止意图)
        pendingMessages.clear()
    }

    fun sendMessage(message: String) {
        val ws = webSocketRef.get()
        // 已连接: 直接发送; send 返回 false 表示底层已不可用, 转走未连接路径入队 + 触发重连
        if (ws != null && _connectionState.value == ConnectionState.CONNECTED) {
            if (ws.send(message)) return
            Log.w(TAG, "WebSocket send 失败, 消息入队等待重连补发")
        }
        // 未连接 / 连接中: 先入队(queue 有序), 再触发连接, onOpen 后统一补发, 避免消息丢失
        pendingMessages.offer(message)
        connect()
    }

    fun sendReconnect() {
        val reconnectMsg = JSONObject().apply {
            put("type", "reconnect")
            put("platform", "android")
            put("timestamp", System.currentTimeMillis())
        }
        sendMessage(reconnectMsg.toString())
    }

    private fun startHeartbeat(intervalSec: Int) {
        stopHeartbeat()
        heartbeatIntervalSec = intervalSec
        heartbeatJob = scope.launch {
            while (isActive) {
                delay(heartbeatIntervalSec * 1000L)
                if (_connectionState.value != ConnectionState.CONNECTED) continue

                // 入站静默检测：服务端每 heartbeat_interval 秒主动 ping、另有秒级状态推送，
                // 超过 3 个心跳周期没有任何入站帧，说明这条连接已"假在线"
                // （弱网单向黑洞 / 被服务端移除）。OkHttp 只在写失败时才报错，
                // 不主动检测的话，断线最长要等 30s 写超时才能感知。
                // 3 倍余量防止与服务端 30s 应用层 ping 的节拍临界竞争误杀。
                val silenceMs = System.currentTimeMillis() - lastInboundAt.get()
                val maxSilenceMs = maxOf(heartbeatIntervalSec, 15) * 3 * 1000L
                if (silenceMs > maxSilenceMs) {
                    Log.w(TAG, "WebSocket 入站静默 ${silenceMs}ms，判定假在线并主动重连")
                    webSocketRef.getAndSet(null)?.close(1000, "heartbeat_timeout")
                    stopHeartbeat()
                    _connectionState.value = ConnectionState.DISCONNECTED
                    scheduleReconnect()
                    break
                }

                val pingMsg = JSONObject().apply {
                    put("type", "ping")
                    put("timestamp", System.currentTimeMillis())
                }
                webSocketRef.get()?.send(pingMsg.toString())
            }
        }
    }

    private fun stopHeartbeat() {
        heartbeatJob?.cancel()
        heartbeatJob = null
    }

    private fun scheduleReconnect() {
        if (manualDisconnect.get()) return
        if (reconnectJob?.isActive == true) return

        reconnectJob = scope.launch {
            val attempt = reconnectAttempts.getAndIncrement()
            val baseDelay = com.aveline.ai.mobile.utils.RetryUtils.calculateExponentialBackoff(
                attempt = attempt,
                initialDelay = 1000,
                multiplier = 1.6,
                maxDelay = 30000
            )
            val jitter = Random.nextLong(0, 500)
            delay(baseDelay + jitter)
            if (manualDisconnect.get()) return@launch

            // 连续失败可能不是「后端挂了」而是「当前通道没了」（出门后局域网不通了），
            // 所以重连前先让裁决器重探一次。
            // 节流由 resolveOnFailure 内部负责（默认 20s 一次），但「当前地址物理上不可能通」
            // （蜂窝 + 私网地址）时会立刻重探 —— 那种情况下多等一秒就多发一秒不出去。
            // 地址真变了会经 changes 广播触发重连，这里就不重复连；没变才按原逻辑重连。
            val before = appPreferences.effectiveBackendUrl
            endpointResolver.resolveOnFailure()
            if (appPreferences.effectiveBackendUrl != before) return@launch

            connect(forceReconnect = true)
        }
    }

    private fun buildWsUrl(backendUrl: String): String {
        // 防御性修复：部分来源（同步/导入/手写）会把 host:port 中的 ':' 编码成 '%3A'，
        // 导致请求 host 变成 "192.0.2.1%3A8000"，服务端无法正确解析。
        // 这里对整段 URL 做一次 URL 解码，把 %3A 还原为 ':'。
        val decoded = try {
            java.net.URLDecoder.decode(backendUrl, StandardCharsets.UTF_8.name())
        } catch (_: Exception) {
            backendUrl
        }

        // 协议头标准化：http(s):// -> ws(s)://，无协议头补 wss://。
        // 见 normalizeWsScheme 的注释说明为何不能用 replaceFirst。
        val wsBase = normalizeWsScheme(decoded)

        var wsUrl = if (wsBase.contains("/api/v1")) {
            if (wsBase.endsWith("/api/v1") || wsBase.endsWith("/api/v1/")) {
                wsBase.trimEnd('/') + "/ws"
            } else {
                wsBase
            }
        } else {
            wsBase.trimEnd('/') + "/api/v1/ws"
        }

        val params = StringBuilder()
        val token = appPreferences.accessToken
        if (token.isNotEmpty()) {
            params.append("token=").append(URLEncoder.encode(token, StandardCharsets.UTF_8.name()))
        }
        val userId = appPreferences.userId
        if (userId.isNotEmpty()) {
            if (params.isNotEmpty()) params.append("&")
            params.append("user_id=").append(URLEncoder.encode(userId, StandardCharsets.UTF_8.name()))
        }

        return if (params.isNotEmpty()) "$wsUrl?${params}" else wsUrl
    }

    private fun parseMessage(text: String, webSocket: WebSocket): WebSocketMessage {
        val json = try { JSONObject(text) } catch (e: Exception) {
            Log.w(TAG, "解析WebSocket消息失败: ${e.message ?: "未知错误"}")
            return WebSocketMessage.Unknown(text)
        }
        val type = json.optString("type")
        val subtype = json.optString("subtype")
        return when (type) {
            "emotion_update" -> {
                val colors = json.optJSONArray("colors")?.let { array ->
                    List(array.length()) { index -> array.optString(index) }
                } ?: emptyList()
                val emotionMix = json.optJSONObject("emotion_mix")?.let { mix ->
                    mix.keys().asSequence().associateWith { key ->
                        mix.optDouble(key, 0.0).toFloat()
                    }
                } ?: emptyMap()
                WebSocketMessage.EmotionUpdate(
                    primary = json.optString("primary"),
                    intensity = json.optDouble("intensity", 0.5).toFloat(),
                    colors = colors,
                    emotionMix = emotionMix
                )
            }
            "connection_established" -> {
                val interval = json.optInt("heartbeat_interval", 30)
                startHeartbeat(interval)
                WebSocketMessage.ConnectionEstablished(
                    heartbeatInterval = interval,
                    reconnectSupported = json.optBoolean("reconnect_supported", true),
                    platform = json.optString("platform", "")
                )
            }
            "reconnect_sync" -> {
                val dataObj = json.optJSONObject("data")
                val emotionState = (dataObj?.optJSONObject("emotion") ?: json.optJSONObject("emotion_state"))?.let { obj ->
                    obj.keys().asSequence().associateWith { key ->
                        kotlinx.serialization.json.JsonPrimitive(obj.get(key).toString())
                    }
                }
                val lifeStatusObj = dataObj?.optJSONObject("life_status") ?: json.optJSONObject("life_status")
                val lifeStatus = lifeStatusObj?.let { obj ->
                    obj.keys().asSequence().associateWith { key ->
                        obj.optDouble(key, 0.0).toFloat()
                    }
                }
                val currentModel = dataObj?.optJSONObject("model")?.optString("model")
                    ?: json.optString("current_model", "")
                WebSocketMessage.ReconnectSync(
                    currentModel = currentModel,
                    emotionState = emotionState,
                    lifeStatus = lifeStatus
                )
            }
            "life_status" -> {
                val dataObj = json.optJSONObject("data") ?: json
                val lifeObj = dataObj.optJSONObject("life") ?: dataObj
                val life = lifeObj.keys().asSequence().associateWith { key ->
                    lifeObj.optDouble(key, 0.0).toFloat()
                }
                val bio = dataObj.optJSONObject("bio")?.let { obj ->
                    obj.keys().asSequence().associateWith { key ->
                        obj.optDouble(key, 0.0).toFloat()
                    }
                } ?: emptyMap()
                WebSocketMessage.LifeStatusUpdate(
                    life = life,
                    bio = bio,
                    mood = dataObj.optString("mood", "calm"),
                    activity = dataObj.optString("activity", "idle"),
                    timestamp = json.optLong("timestamp", System.currentTimeMillis())
                )
            }
            "ritual_event" -> WebSocketMessage.RitualEvent(
                id = json.optString("id"),
                content = json.optString("content"),
                timestamp = json.optLong("timestamp", System.currentTimeMillis()),
                // 归属角色：老后端不下发这两个字段，客户端按默认标题 + 聊天主页兜底
                profileFilename = json.optString("profile_filename").ifEmpty { null },
                roleName = json.optString("role_name").ifEmpty { null }
            )
            "spontaneous_reaction" -> WebSocketMessage.SpontaneousReaction(
                id = json.optString("id"),
                content = json.optString("content"),
                timestamp = json.optLong("timestamp", System.currentTimeMillis()),
                profileFilename = json.optString("profile_filename").ifEmpty { null },
                roleName = json.optString("role_name").ifEmpty { null }
            )
            "phone_action" -> {
                val paramsObj = json.optJSONObject("params")
                val paramsMap = paramsObj?.keys()?.asSequence()?.associateWith { key ->
                    kotlinx.serialization.json.JsonPrimitive(paramsObj.get(key).toString())
                } ?: emptyMap()
                WebSocketMessage.PhoneActionCommand(
                    actionId = json.optString("action_id", json.optString("actionId", "")),
                    actionType = json.optString("action_type", json.optString("actionType", "")),
                    params = kotlinx.serialization.json.JsonObject(paramsMap)
                )
            }
            "device_command" -> {
                // 设备控制指令 (后端下发, 手机前端执行)
                val argsObj = json.optJSONObject("args")
                val argsMap = argsObj?.keys()?.asSequence()?.associateWith { key ->
                    val value = argsObj.get(key)
                    when (value) {
                        is String -> kotlinx.serialization.json.JsonPrimitive(value)
                        is Int -> kotlinx.serialization.json.JsonPrimitive(value)
                        is Long -> kotlinx.serialization.json.JsonPrimitive(value)
                        is Double -> kotlinx.serialization.json.JsonPrimitive(value)
                        is Boolean -> kotlinx.serialization.json.JsonPrimitive(value)
                        else -> kotlinx.serialization.json.JsonPrimitive(value.toString())
                    }
                } ?: emptyMap()
                WebSocketMessage.DeviceCommand(
                    requestId = json.optString("request_id", json.optString("requestId", "")),
                    command = json.optString("command", ""),
                    args = kotlinx.serialization.json.JsonObject(argsMap),
                    timeout = json.optInt("timeout", 30)
                )
            }
            "image_result" -> {
                // 后端 image_result 把图片字段嵌套在 data 子对象里
                // （与 _generate_image_and_send / _send_media_image_result 一致）
                // 兼容旧格式：顶层 image_url/url（万一某些路径仍直发顶层）
                val dataObj = json.optJSONObject("data")
                val url = buildString {
                    val fromData = dataObj?.let { d ->
                        d.optString("image_url", "").ifEmpty { d.optString("url", "") }
                    } ?: ""
                    if (fromData.isNotEmpty()) append(fromData)
                    else {
                        val fromTop = json.optString("image_url", "").ifEmpty { json.optString("url", "") }
                        if (fromTop.isNotEmpty()) append(fromTop)
                    }
                }
                // 拿不到图片地址时不要下发 ImageResult：空地址会让前端渲染出
                // 一个加载失败的图片气泡（破图占位），这里直接降级为 Unknown 丢弃。
                if (url.isBlank()) {
                    Log.w(TAG, "image_result 缺少图片地址，已忽略")
                    WebSocketMessage.Unknown(rawJson = text)
                } else {
                    WebSocketMessage.ImageResult(imageUrl = url)
                }
            }
            "video_result" -> {
                // 与 image_result 同构：字段嵌套在 data 子对象里，兼容顶层直发。
                val dataObj = json.optJSONObject("data")
                val url = dataObj?.let { d ->
                    d.optString("video_url", "").ifEmpty { d.optString("url", "") }
                }?.takeIf { it.isNotEmpty() }
                    ?: json.optString("video_url", "").ifEmpty { json.optString("url", "") }
                // 空地址不该下发 VideoResult：前端会渲染出一个永远加载失败的气泡。
                if (url.isBlank()) {
                    Log.w(TAG, "video_result 缺少视频地址，已忽略")
                    WebSocketMessage.Unknown(rawJson = text)
                } else {
                    WebSocketMessage.VideoResult(videoUrl = url)
                }
            }
            "notification" -> WebSocketMessage.Notification(
                title = json.optString("title"),
                // 后端历史上一直发 `content`（vocabulary.py / 各类推送），这里只读
                // `body` 会拿到空串 —— 通知栏弹出来标题有了、正文却是空的。
                // 两个字段都认，谁有值用谁。
                body = json.optString("body").ifEmpty { json.optString("content") },
                // 后端下发的精确跳转目标；缺失时仍由客户端按内容启发式兜底。
                target = json.optString("target").ifEmpty { null },
                sessionId = json.optString("session_id").ifEmpty { null }
            )
            // 角色主动消息（Active Care / 自发开口）。此前缺这一分支，
            // 整条消息会落到 Unknown 被静默丢弃，导致既不上屏也不通知。
            "proactive_message" -> WebSocketMessage.ProactiveMessage(
                content = json.optString("content"),
                conversationId = json.optString("conversation_id").ifEmpty { null },
                messageType = json.optString("message_type").ifEmpty { "text" },
                messageId = json.optString("message_id").ifEmpty { null },
                isPeerScript = json.optBoolean("is_peer_script", false),
                peerSpeaker = json.optString("peer_speaker").ifEmpty { null },
                // 说话角色的人设文件名：App 归档消息到对应角色会话要用它，
                // 缺失时客户端回退用 conversation_id 解析 role 再查本地偏好。
                profileFilename = json.optString("profile_filename").ifEmpty { null },
                // 说话角色中文名：通知标题用（本地自定义昵称优先于它）
                roleName = json.optString("role_name").ifEmpty { null }
            )
            "message" -> when (subtype) {
                "response_done" -> WebSocketMessage.ResponseDone
                "response_chunk" -> WebSocketMessage.ResponseChunk(
                    content = json.optString("content"),
                    chunkIndex = json.optInt("chunk_index", 0),
                    emotion = json.optString("emotion").ifEmpty { null }
                )
                else -> WebSocketMessage.TextMessage(
                    text = json.optString("content", json.optString("text", text)),
                    emotion = json.optString("emotion").ifEmpty { null }
                )
            }
            "error" -> WebSocketMessage.Error(
                // 后端业务错误同时下发 message 与 content（后者供 iOS），
                // 任取其一，避免只认一个字段时 Android 拿到空文案。
                message = json.optString("message")
                    .ifEmpty { json.optString("content") }
                    .ifEmpty { json.optString("error", "连接错误") },
                errorCode = json.optString("error_code").ifEmpty { null }
            )
            "pong" -> WebSocketMessage.Pong(timestamp = System.currentTimeMillis())
            // 回应服务端下发的应用层 ping，保证双端心跳对称。
            // 服务端 HeartbeatMixin.heartbeat_checker 每 heartbeat_interval 秒给连接发
            // {"type":"ping"}，若 60s 内收不到客户端 pong 会主动 close(1001) 误杀健康连接。
            // 虽然本端也会主动发 ping 并收到服务端 pong（刷新 last_heartbeat），但对称回应可
            // 彻底消除任何时序竞态，避免单边心跳失败导致断连。
            "ping" -> {
                val pongMsg = JSONObject().apply {
                    put("type", "pong")
                    put("timestamp", json.optLong("timestamp", System.currentTimeMillis()))
                }
                // 必须用收到 ping 的这条连接回 pong（不能用 webSocketRef：
                // 重连后的旧连接会拿到新 socket，导致那条连接永远不回心跳）
                webSocket.send(pongMsg.toString())
                WebSocketMessage.Pong(timestamp = System.currentTimeMillis())
            }
            else -> WebSocketMessage.Unknown(text)
        }
    }
}
