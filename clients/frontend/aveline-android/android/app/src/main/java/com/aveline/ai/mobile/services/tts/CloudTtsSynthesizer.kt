package com.aveline.ai.mobile.services.tts

import android.os.SystemClock
import android.util.Base64
import android.util.Log
import com.aveline.ai.mobile.data.remote.dto.TtsDirectConfigDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonObject
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.UUID
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 安卓端直连云端 TTS。
 *
 * 为什么需要它：原来的链路是「Android -> 后端 -> 云端 TTS -> 后端 base64 回传」，
 * 音频要在后端多落地/编码一次，走公网时等于多绕一跳。这里让客户端拿着
 * `/api/v1/media/tts/direct-config` 下发的配置直接请求云端，音频数据不经过后端。
 *
 * 支持两类云端接口：
 * - 火山引擎 v1（`https://openspeech.bytedance.com/api/v1/tts`，返回 base64 MP3）；
 * - OpenAI 兼容 `/v1/audio/speech`（siliconflow / openai / custom，返回二进制音频）。
 *
 * 任何失败都返回 null，由 [com.aveline.ai.mobile.services.TTSEngine] 回退到后端合成，
 * 保证「直连只是加速，不是单点」。
 */
@Singleton
class CloudTtsSynthesizer @Inject constructor(
    private val configRepository: CloudTtsConfigRepository
) {
    companion object {
        private const val TAG = "CloudTtsSynthesizer"
        private const val VOLCANO_BASE_URL = "https://openspeech.bytedance.com/api/v1/tts"
        private const val VOLCANO_SUCCESS_CODE = 3000
        /** 连续失败达到该次数后暂停直连一段时间，避免每次播报都先等一次超时。 */
        private const val FAILURE_THRESHOLD = 2
        private const val FAILURE_COOLDOWN_MS = 5 * 60 * 1000L
        private val VOLCANO_PROVIDERS = setOf("volcano", "volcengine", "字节")
        private val OPENAI_PROVIDERS = setOf("cloud", "siliconflow", "openai", "custom")
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
    }

    /** 直连合成的音频结果：字节 + 文件扩展名（mp3/wav）。 */
    data class AudioChunk(val bytes: ByteArray, val extension: String)

    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
    }

    // 专用 client：不能复用后端的 OkHttpClient —— 它有 baseUrl 拦截器会把
    // 云端域名改写成后端地址，直连就变成绕回后端了。
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(45, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    // 连续失败熔断：云端被网络/额度问题挡住时，后续播报直接走后端，别每次都等超时
    @Volatile
    private var consecutiveFailures = 0

    @Volatile
    private var disabledUntil = 0L

    /**
     * 尝试直连合成。
     *
     * @param text 原始文本（内部会做与后端一致的清洗）
     * @param voiceSelector `voice:<角色名>`、音色名、音色 ID 或参考音频路径
     * @return 成功返回音频；未启用 / 失败返回 null
     */
    suspend fun synthesize(
        text: String,
        voiceSelector: String?,
        speed: Float = 1.0f
    ): AudioChunk? {
        if (SystemClock.elapsedRealtime() < disabledUntil) return null
        val config = configRepository.get()?.takeIf { it.enabled } ?: return null
        val cleaned = TtsTextSanitizer.clean(text)
        if (cleaned.isBlank()) return null

        return withContext(Dispatchers.IO) {
            val result = runCatching {
                when (config.provider.trim().lowercase()) {
                    in VOLCANO_PROVIDERS ->
                        requestVolcano(config, cleaned, voiceSelector, speed)
                    in OPENAI_PROVIDERS ->
                        requestOpenAiCompatible(config, cleaned, voiceSelector, speed)
                    else -> null
                }
            }.onFailure {
                // 不打印请求头/凭据，只留失败原因
                Log.w(TAG, "直连 TTS 失败(provider=${config.provider}): ${it.message}")
            }.getOrNull()

            if (result != null) {
                consecutiveFailures = 0
            } else {
                consecutiveFailures++
                if (consecutiveFailures >= FAILURE_THRESHOLD) {
                    disabledUntil = SystemClock.elapsedRealtime() + FAILURE_COOLDOWN_MS
                    consecutiveFailures = 0
                    Log.w(TAG, "直连 TTS 连续失败，暂停直连 5 分钟，期间走后端合成")
                }
            }
            result
        }
    }

    // ==================== 火山引擎 ====================

    private data class VolcanoVoice(
        val voiceId: String,
        val apiKey: String,
        val appid: String
    )

    private fun requestVolcano(
        config: TtsDirectConfigDto,
        text: String,
        voiceSelector: String?,
        speed: Float
    ): AudioChunk? {
        val voice = resolveVolcanoVoice(config, voiceSelector)
        if (voice.apiKey.isBlank()) return null

        val payload = buildJsonObject {
            putJsonObject("app") {
                put("appid", voice.appid)
                put("cluster", config.cluster.ifBlank { "volcano_icl" })
            }
            putJsonObject("user") { put("uid", "aveline_android") }
            putJsonObject("audio") {
                put("voice_type", voice.voiceId)
                put("encoding", config.encoding.ifBlank { "mp3" })
                put("speed_ratio", speed.coerceIn(0.5f, 2.0f).toDouble())
            }
            putJsonObject("request") {
                put("reqid", UUID.randomUUID().toString())
                put("text", text)
                put("operation", "query")
            }
        }

        val url = config.base_url.trim().ifBlank { VOLCANO_BASE_URL }
        val request = Request.Builder()
            .url(url)
            .addHeader("Content-Type", "application/json")
            .addHeader("X-Api-Resource-Id", config.resource_id.ifBlank { "volc.megatts.voiceclone" })
            .addHeader("x-api-key", voice.apiKey)
            .post(payload.toString().toRequestBody(JSON_MEDIA_TYPE))
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                Log.w(TAG, "火山 TTS HTTP ${response.code}")
                return null
            }
            val body = response.body?.bytes() ?: return null
            val contentType = response.header("Content-Type").orEmpty()
            if (!contentType.contains("json", ignoreCase = true)) {
                // 兼容个别网关直接返回音频二进制的情况
                return body.takeIf { it.isNotEmpty() }?.let { AudioChunk(it, "mp3") }
            }

            val root = json.parseToJsonElement(body.toString(Charsets.UTF_8)).jsonObject
            val code = root["code"]?.jsonPrimitive?.intOrNull
            if (code != VOLCANO_SUCCESS_CODE) {
                Log.w(TAG, "火山 TTS 业务错误 code=$code message=${root["message"]}")
                return null
            }
            val encoded = root["data"]?.jsonPrimitive?.contentOrNull ?: return null
            val audio = Base64.decode(encoded, Base64.DEFAULT)
            return audio.takeIf { it.isNotEmpty() }?.let { AudioChunk(it, "mp3") }
        }
    }

    private fun resolveVolcanoVoice(
        config: TtsDirectConfigDto,
        voiceSelector: String?
    ): VolcanoVoice {
        var raw = voiceSelector.orEmpty().trim()
        if (raw.startsWith("voice:", ignoreCase = true)) {
            raw = raw.substringAfter(':').trim()
        }

        // 别名归一（Aveline / Aveline -> Aveline），规则由后端下发
        val canonical = config.aliases.entries
            .firstOrNull { it.key.equals(raw, ignoreCase = true) }
            ?.value
            ?: raw

        val mapped = config.voice_map[canonical] ?: config.voice_map[raw]
        val fallbackName = config.fallback_voice.ifBlank { "Aveline" }
        val fallbackId = config.voice_map[fallbackName] ?: config.default_voice

        val voiceId = mapped
            ?: canonical.takeIf { looksLikeVoiceId(it) }
            ?: fallbackId

        val voiceKey = config.key_map[canonical] ?: config.key_map[raw]
        return VolcanoVoice(
            voiceId = voiceId,
            apiKey = voiceKey?.api_key?.takeIf { it.isNotBlank() } ?: config.api_key,
            appid = voiceKey?.appid?.takeIf { it.isNotBlank() } ?: config.appid
        )
    }

    /** 与后端 `_looks_like_voice_id` 同口径：ASCII 且只含字母数字/下划线/短横线。 */
    private fun looksLikeVoiceId(value: String): Boolean {
        if (value.length < 4 || !value.all { it.code < 128 }) return false
        return value.all { it.isLetterOrDigit() || it == '_' || it == '-' }
    }

    // ==================== OpenAI 兼容 ====================

    private fun requestOpenAiCompatible(
        config: TtsDirectConfigDto,
        text: String,
        voiceSelector: String?,
        speed: Float
    ): AudioChunk? {
        if (config.api_key.isBlank() || config.base_url.isBlank()) return null

        val voice = resolveOpenAiVoice(config, voiceSelector)
        val payload = buildJsonObject {
            put("model", config.model)
            put("input", text)
            put("voice", voice)
            if (speed != 1.0f) {
                put("speed", speed.coerceIn(0.5f, 2.0f).toDouble())
            }
        }

        val request = Request.Builder()
            .url(normalizeSpeechUrl(config.base_url))
            .addHeader("Content-Type", "application/json")
            .addHeader("Authorization", "Bearer ${config.api_key}")
            .post(payload.toString().toRequestBody(JSON_MEDIA_TYPE))
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                Log.w(TAG, "OpenAI 兼容 TTS HTTP ${response.code}")
                return null
            }
            val body = response.body?.bytes() ?: return null
            if (body.isEmpty()) return null
            return AudioChunk(body, extensionOf(response.header("Content-Type")))
        }
    }

    private fun resolveOpenAiVoice(config: TtsDirectConfigDto, voiceSelector: String?): String {
        var raw = voiceSelector.orEmpty().trim()
        if (raw.startsWith("voice:", ignoreCase = true)) {
            raw = raw.substringAfter(':').trim()
        }
        if (raw.isBlank()) return config.default_voice.ifBlank { "alloy" }
        // OpenAI 兼容接口的 voice 就是音色 ID（alloy / nova ...），直接用
        return raw
    }

    /**
     * 与后端 `synthesize_cloud_tts_bytes` 一致：
     * 已以 `speech` 结尾则原样；以 `/v1` 结尾补 `/audio/speech`；其余补 `/v1/audio/speech`。
     */
    private fun normalizeSpeechUrl(raw: String): String {
        val url = raw.trim().trimEnd('/')
        return when {
            url.endsWith("speech") -> url
            url.endsWith("/v1") -> "$url/audio/speech"
            else -> "$url/v1/audio/speech"
        }
    }

    private fun extensionOf(contentType: String?): String {
        val type = contentType.orEmpty().lowercase()
        return when {
            type.contains("wav") -> "wav"
            type.contains("ogg") -> "ogg"
            type.contains("aac") -> "aac"
            type.contains("flac") -> "flac"
            else -> "mp3"
        }
    }
}
