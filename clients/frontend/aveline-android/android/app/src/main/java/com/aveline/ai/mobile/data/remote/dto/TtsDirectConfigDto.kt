package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.Serializable

/**
 * 客户端直连云端 TTS 的配置（`GET /api/v1/media/tts/direct-config`）。
 *
 * 后端只在 provider 是云端 TTS 时返回 `enabled=true`；本地引擎
 * （qwen3 / gpt_sovits / f5）返回 false，客户端据此回退到
 * `POST /api/v1/media/tts`，保证两种链路都能出声。
 *
 * 所有字段都给默认值：后端裁剪字段时不应让整个响应反序列化失败。
 */
@Serializable
data class TtsDirectConfigResponse(
    val status: String = "",
    val data: TtsDirectConfigDto? = null
)

@Serializable
data class TtsDirectConfigDto(
    val enabled: Boolean = false,
    val provider: String = "",
    val base_url: String = "",
    val api_key: String = "",
    /** 火山引擎旧版鉴权使用；新版 x-api-key 仍会带上它。 */
    val appid: String = "",
    val resource_id: String = "",
    val cluster: String = "volcano_icl",
    val model: String = "",
    val default_voice: String = "",
    /** 音色名解析不到时后端实际使用的角色名（火山默认 Aveline）。 */
    val fallback_voice: String = "",
    val encoding: String = "mp3",
    /** 角色名 -> 云端音色 ID。 */
    val voice_map: Map<String, String> = emptyMap(),
    /** 角色名 -> 独立凭据（多音色多账号时使用）。 */
    val key_map: Map<String, TtsVoiceKeyDto> = emptyMap(),
    /** 角色别名 -> 权威音色名（与后端引擎同源）。 */
    val aliases: Map<String, String> = emptyMap(),
    /** enabled=false 时的原因，仅用于日志。 */
    val reason: String = ""
)

@Serializable
data class TtsVoiceKeyDto(
    val api_key: String = "",
    val appid: String = ""
)
