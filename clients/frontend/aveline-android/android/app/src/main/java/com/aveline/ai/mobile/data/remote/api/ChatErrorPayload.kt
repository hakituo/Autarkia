package com.aveline.ai.mobile.data.remote.api

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import retrofit2.HttpException
import java.io.IOException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

/**
 * 把后端各条错误通道统一翻译成 [StreamEvent.Error]。
 *
 * 用户要求「后端怎么给就怎么显示」，所以这里只做**搬运与拼接**，不自己编结论：
 * - 主句优先用后端的 `message`（没有才退回 `error` / `detail`）
 * - 错误码用 `error_code`
 * - 详情用 `details.raw_error` / `details.error_message` / `details.upstream_body` 等原始串
 * - HTTP 非 2xx 时额外带上状态码（上一版只拼 reason phrase，422 只剩 "Unprocessable Entity"）
 */
private const val MAX_DETAIL_CHARS = 300

private val errorJson = Json {
    ignoreUnknownKeys = true
    isLenient = true
}

/** 解析后端错误 JSON：SSE `type=error` 事件体、HTTP 错误体、裸 JSON 错误都走这里。 */
internal fun errorFromJsonObject(obj: JsonObject, httpStatus: Int? = null): StreamEvent.Error {
    val message = firstText(obj, "message", "error", "detail") ?: "未知错误"
    return StreamEvent.Error(
        message = message,
        errorCode = firstText(obj, "error_code", "code"),
        detail = buildDetailText(obj["details"] as? JsonObject, message),
        httpStatus = httpStatus,
    )
}

/**
 * HTTP 非 2xx：读 errorBody 再解析。
 *
 * 后端在非 2xx 时有三种错误体：chat 路由的统一结构
 * （`message` / `error_code` / `details`）、FastAPI 的原生 422
 * （`detail` 是数组）、安全中间件（`{"success":false,"error":"..."}`）。
 * 三种都能被 [errorFromJsonObject] 兜住；不是 JSON 时按原文截断显示，别让用户只看到一个状态码。
 */
internal fun errorFromHttpResponse(
    code: Int,
    reason: String,
    body: String?,
): StreamEvent.Error {
    val raw = body?.trim().orEmpty()
    val obj = if (raw.startsWith("{")) {
        runCatching { errorJson.parseToJsonElement(raw).jsonObject }.getOrNull()
    } else {
        null
    }
    if (obj != null) return errorFromJsonObject(obj, httpStatus = code)
    return StreamEvent.Error(
        message = raw.ifBlank { reason.ifBlank { "请求失败" } }.take(MAX_DETAIL_CHARS),
        httpStatus = code,
    )
}

/**
 * 本地异常：[action] 说明这一步在做什么（读取流失败 / 请求失败），
 * 后面跟分类后的原因，详情里保留异常类名与原始 message。
 */
internal fun errorFromThrowable(e: Throwable, action: String): StreamEvent.Error {
    if (e is HttpException) {
        val body = runCatching { e.response()?.errorBody()?.string() }.getOrNull()
        return errorFromHttpResponse(e.code(), e.message(), body)
    }
    val friendly = when (e) {
        is SocketTimeoutException -> "请求超时，服务器没有在预期时间内响应"
        is UnknownHostException -> "找不到服务器地址，请检查网络或服务地址"
        is IOException -> "网络连接中断"
        else -> "内部错误"
    }
    val detail = buildString {
        append(e.javaClass.simpleName)
        e.message?.takeIf { it.isNotBlank() }?.let { append(": ").append(it) }
    }
    return StreamEvent.Error(
        message = "$action: $friendly",
        detail = detail.take(MAX_DETAIL_CHARS),
    )
}

private fun firstText(obj: JsonObject, vararg keys: String): String? {
    for (key in keys) {
        val text = obj[key]?.readableText()?.takeIf { it.isNotBlank() } ?: continue
        return text
    }
    return null
}

/** 把 JSON 值压成一行可读文本：FastAPI 的 422 `detail` 是数组，不能直接取 jsonPrimitive。 */
private fun JsonElement.readableText(): String? = when (this) {
    is JsonPrimitive -> contentOrNull
    is JsonArray -> mapNotNull { it.readableText() }.joinToString("；").ifBlank { null }
    is JsonObject -> {
        val msg = this["msg"]?.jsonPrimitive?.contentOrNull
        val loc = (this["loc"] as? JsonArray)
            ?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
            ?.joinToString(".")
        when {
            msg != null && !loc.isNullOrBlank() -> "$loc: $msg"
            msg != null -> msg
            else -> null
        }
    }
    else -> null
}

/**
 * 详情只保留后端原始错误串，且与主句重复时不再重复展示。
 *
 * 上游 422 的信息分散在三处：`upstream_status=422`、`upstream_body="input new_sensitive (1026)"`、
 * `raw_error="API returned 422"`。只取第一个的话关键的那句 body 会被吞掉，所以按顺序拼起来。
 */
private fun buildDetailText(details: JsonObject?, message: String): String? {
    if (details == null) return null
    val parts = mutableListOf<String>()
    details["upstream_status"]?.readableText()?.let { parts += "上游 HTTP $it" }
    val body = firstDetailText(details, "upstream_body", "body")
    body?.let { parts += it }
    val raw = firstDetailText(details, "raw_error", "error_message", "upstream_raw")
    if (raw != null && raw != body) parts += raw
    val text = parts.joinToString(" · ").trim()
    if (text.isBlank() || text == message.trim()) return null
    return text.take(MAX_DETAIL_CHARS)
}

private fun firstDetailText(details: JsonObject, vararg keys: String): String? {
    for (key in keys) {
        val text = details[key]?.readableText()?.takeIf { it.isNotBlank() } ?: continue
        return text
    }
    return null
}
