# 接口层（HTTP / WebSocket / OpenAI 兼容）

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](README.md)

---

## 7. 接口层技术详解

## 7.1 HTTP API规范

**基础URL**: `http://localhost:8000/api/v1`

**请求格式**:

```json
{
    "message": "用户消息",
    "conversation_id": "conv_123",
    "user_id": "user_456",
    "context": {}
}
```

**响应格式**:

```json
{
    "status": "success",
    "data": {},
    "timestamp": "2026-03-12T10:00:00Z"
}
```

**错误响应**:

```json
{
    "status": "error",
    "error": {
        "code": "INTERNAL_ERROR",
        "message": "错误描述",
        "details": {}
    },
    "timestamp": "2026-03-12T10:00:00Z"
}
```

**安全基线（公网部署）**:

- 受保护路径：`/api/**`、`/v1/**`、`/demo**`
- HTTP 认证方式：`Authorization: Bearer <token>`（兼容 `X-Internal-Token` / `X-Access-Token`）
- 密钥来源：`XIAOYOU_SECURITY_WEB_ACCESS_TOKEN`
- 未配置密钥时，受保护路径返回 `503`（拒绝访问，防止裸奔）
- WebSocket `/api/v1/ws` 在握手前执行同一 Token 校验（支持 `token` 查询参数），失败返回 `1008`
- 请求治理：按 `server.max_content_length` 做请求体大小限制，按 `max_requests_per_minute` 与 `max_ip_requests_per_minute` 做 60 秒窗口限流

## 7.2 WebSocket协议

**连接URL**: `ws://localhost:8000/api/v1/ws?token=xxx&user_id=xxx`

**消息类型**:

| 类型             | 方向            | 说明     |
| -------------- | ------------- | ------ |
| `ping`         | Server→Client | 心跳检测   |
| `pong`         | Client→Server | 心跳响应   |
| `chat`         | 双向            | 聊天消息   |
| `stream`       | Server→Client | 流式响应（逐块 token） |
| `response_reset` | Server→Client | 工具调用开始：清空当前临时消息 |
| `notification` | Server→Client | 主动关怀通知 |
| `status`       | Server→Client | 状态更新   |

**双 QQ 主动消息可靠投递**:
- 逻辑会话使用 `shared__persona__{role}`，WebSocket 广播与离线队列必须使用真实主人传输 ID（`private_{master_qq_id}`），不得使用 `shared__scope__*`。
- 同一主人下的多角色连接用 `client_id=qq_{role_id}_{session_id}` 区分；实时广播和离线重放都只交给目标角色连接，发送失败的离线消息保留到下次重连。
- 协议心跳为 30 秒间隔、60 秒超时；Windows `WinError 121` 作为可恢复断连记录，不输出误导性的完整错误堆栈。

**消息格式**:

```json
{
    "type": "chat",
    "data": {
        "content": "消息内容",
        "emotion": "happy",
        "is_streaming": false
    },
    "timestamp": 1710230400000
}
```

**连续消息合并策略**:
- WebSocket 侧默认仍支持 `server.ws_user_message_merge_wait_ms` 连续消息合并
- `server.ws_skip_merge_wait_platforms` 可按平台跳过二次等待，默认包含 `qq`
- QQ 适配器发送 `text_input` 时可显式携带 `skip_merge_wait=true`，优先级高于平台配置

**真流式响应事件时序**:

对话回复按以下时序逐块推送（HTTP SSE 与 WebSocket 两条通道共用同一套事件语义）：

| 阶段 | 事件 | 前端行为 |
|------|------|---------|
| 普通文本 | `token`（逐字符） | 立即追加到当前生成中的消息 |
| AI 开始调用工具 | `response_reset` | 清空当前生成中的临时消息（不影响历史消息） |
| 工具执行完成 | `token`（逐字符） | 最终回答继续逐块追加 |
| 全部完成 | `response_done` | 标记消息完成；后端此时才把完整结果写入数据库 |

**关键规则**:

- 普通文本每产生一个字符就立即推送，不等待整轮结束，实现「真流式」。
- `response_reset` 只在工具调用轮次出现：后端先 `yield {"type":"response_reset"}`，随后 `discard_turn()` 丢弃中间轮次缓冲（工具调用前的半句已实时送达前端，由 reset 清空），最终回答从头逐块重发。
- 落库（`_save_conversation_history`）严格推迟到 `response_done` 之后调度，保证写入的是完整结果。
- 客户端（Android）收到 `response_reset` 只清空当前正在生成的那条消息，历史消息保持不动（见 `ChatFlushManager.onResponseReset()`）。

> **实现位置**: `core/agents/chat_agent_components/streaming.py`（`stream_chat_impl` 事件产出）、`streaming_pipeline/tag_stream_parser.py`（token 实时队列 `rt_emits`）、`core/services/aveline/stream_orchestrator.py`（事件编排与 SSE 映射）

## 7.3 OpenAI兼容API

**路径**: `/v1/chat/completions`

**请求格式**:

```json
{
    "model": "qwen-7b",
    "messages": [
        {"role": "user", "content": "你好"}
    ],
    "stream": true,
    "temperature": 0.7,
    "max_tokens": 2048
}
```
