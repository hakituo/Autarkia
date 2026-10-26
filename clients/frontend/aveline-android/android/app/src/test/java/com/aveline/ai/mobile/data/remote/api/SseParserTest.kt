package com.aveline.ai.mobile.data.remote.api

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * SseParser 的回归测试。
 *
 * 覆盖历史 bug：后端 `routers/v1/chat.py` 有一部分错误分支（content 为空 /
 * 内容过长 / 消息格式非法）走的是 `return resp` 返回**普通 JSON**，HTTP 状态码
 * 仍是 200，并不是 SSE 流。旧实现强制要求行以 `data: ` 开头，于是整段 JSON
 * 被静默丢掉：一个 StreamEvent 都不发，UI 停在「正在输入」且**不弹任何错误**，
 * 安卓端表现为「AI 完全不回复」。
 *
 * 发图不带文案时 caption 为空串，正好命中 EMPTY_CONTENT 分支，
 * 就是这条静默路径导致的（与 d09261d 修的那条链路叠加）。
 */
class SseParserTest {

    @Test
    fun `正常 SSE chunk 解析为 Chunk`() {
        val line = """data: {"type":"message","subtype":"response_chunk","content":"你好"}"""
        assertEquals(StreamEvent.Chunk("你好"), SseParser.parse(line))
    }

    @Test
    fun `DONE 标记解析为 Done`() {
        assertEquals(StreamEvent.Done(), SseParser.parse("data: [DONE]"))
    }

    @Test
    fun `SSE 内的 error 事件解析为 Error`() {
        val line = """data: {"type":"error","message":"生成失败"}"""
        assertEquals(StreamEvent.Error("生成失败"), SseParser.parse(line))
    }

    /** 后端 EMPTY_CONTENT 分支真实返回的响应体（HTTP 200，非 SSE）。 */
    @Test
    fun `裸 JSON 错误响应兜底为 Error 且带上 error_code`() {
        val bare =
            """{"status":"error","message":"消息内容不能为空且必须是字符串",""" +
                """"detail":"消息内容不能为空且必须是字符串",""" +
                """"error":"消息内容不能为空且必须是字符串",""" +
                """"error_code":"EMPTY_CONTENT","details":{},"request_id":"abc","timestamp":1.0}"""
        val event = SseParser.parse(bare)
        assertTrue("裸 JSON 错误必须被识别，实际=$event", event is StreamEvent.Error)
        val error = event as StreamEvent.Error
        assertEquals("EMPTY_CONTENT", error.errorCode)
        assertTrue("展示文案要带 error_code，实际=${error.describe()}", error.describe().contains("EMPTY_CONTENT"))
        assertTrue("错误要带可读文案，实际=${error.describe()}", error.describe().contains("消息内容不能为空"))
    }

    @Test
    fun `裸 JSON 错误没有 error_code 时只回退文案`() {
        val bare = """{"status":"error","message":"服务暂时不可用"}"""
        assertEquals(StreamEvent.Error("服务暂时不可用"), SseParser.parse(bare))
    }

    /** FastAPI 校验错误的 detail 是数组，不能因为取 jsonPrimitive 而抛异常，且要把 msg 读出来。 */
    @Test
    fun `detail 为数组的校验错误能读出 FastAPI 的 msg`() {
        val bare = """{"detail":[{"loc":["body"],"msg":"field required","type":"value_error"}]}"""
        val event = SseParser.parse(bare)
        assertTrue("detail 数组要能解析成文案，实际=$event", event is StreamEvent.Error)
        val message = (event as StreamEvent.Error).message
        assertTrue("要带上 FastAPI 的 msg，实际=$message", message.contains("field required"))
        assertTrue("要带上出错字段位置，实际=$message", message.contains("body"))
    }

    /** 后端 error 事件里的 error_code 与 details 必须一起展示，别再只剩一句笼统文案。 */
    @Test
    fun `SSE error 事件带出 error_code 与上游详情`() {
        val line =
            """data: {"type":"error","message":"这次输入被上游模型判定为敏感内容而拒绝（HTTP 422）",""" +
                """"error_code":"non_retryable","details":{"error_type":"LLMStreamError",""" +
                """"raw_error":"API returned 422","upstream_status":422,""" +
                """"upstream_body":"input new_sensitive (1026)"}}"""
        val error = SseParser.parse(line) as StreamEvent.Error
        assertEquals("non_retryable", error.errorCode)
        val text = error.describe()
        assertTrue("要显示错误码，实际=$text", text.contains("non_retryable"))
        assertTrue("要显示上游状态码，实际=$text", text.contains("422"))
        assertTrue("要显示上游原话，实际=$text", text.contains("new_sensitive"))
    }

    /** HTTP 非 2xx 的后端原因在 errorBody 里，422 不能只显示 "Unprocessable Entity"。 */
    @Test
    fun `HTTP 422 errorBody 读得出后端原因`() {
        val body = """{"detail":[{"loc":["body","message"],"msg":"Field required"}]}"""
        val error = errorFromHttpResponse(422, "Unprocessable Entity", body)
        assertEquals(422, error.httpStatus ?: -1)
        val text = error.describe()
        assertTrue("要显示 HTTP 状态码，实际=$text", text.contains("HTTP 422"))
        assertTrue("要显示后端原因，实际=$text", text.contains("Field required"))
    }

    /** 非 JSON 的错误体也不能只剩一个状态码。 */
    @Test
    fun `HTTP 非 2xx 非 JSON 错误体保留原文`() {
        val error = errorFromHttpResponse(502, "Bad Gateway", "<html>bad gateway</html>")
        assertTrue("要保留原始错误体，实际=${error.describe()}", error.describe().contains("bad gateway"))
    }

    /** 成功响应不应该被当成错误，否则会把一次正常回复变成报错。 */
    @Test
    fun `成功的裸 JSON 不会被误判为 Error`() {
        val bare = """{"status":"success","response":"在。","request_id":"abc"}"""
        assertNull(SseParser.parse(bare))
    }

    @Test
    fun `空行与注释行忽略`() {
        assertNull(SseParser.parse(""))
        assertNull(SseParser.parse("   "))
        assertNull(SseParser.parse(": keep-alive"))
    }

    @Test
    fun `非 JSON 的 data 行忽略`() {
        assertNull(SseParser.parse("data: not-json"))
        assertNull(SseParser.parse("data: "))
    }
}
