"""验证上游流式失败一定会变成前端可见的报错事件。

2026-10-21：SiliconFlow 持续 `Stream Request Failed`，App 既不回复也不报错。
断点三处：provider 的 `{"error": ...}` chunk 被 process_chunk 静默丢弃；
空回复时 stream_chat_impl 直接 yield done；WS `_send_error` 发
`type: message / subtype: response` 被各端当普通消息渲染。

运行：
    venv_cpu\\Scripts\\python.exe tests\\scripts\\streaming_refactor\\verify_upstream_stream_error_surfaces.py
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

FAILED = []


def check(condition: bool, desc: str) -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {desc}")
    if not condition:
        FAILED.append(desc)


# ---------------------------------------------------------------- dummy 组件


class DummyEmotionManager:
    def ingest_life_stats(self, *args, **kwargs):
        return None

    def process_text(self, *args, **kwargs):
        return None

    def build_dialogue_affect_instruction(self, **kwargs):
        return ""


class DummyToolRegistry:
    def get_active_tools(self):
        return []

    def get_openai_tools(self, *args, **kwargs):
        return None

    def get_tool(self, name):
        return None


class FixedLLM:
    """按预设脚本吐 chunk；脚本为空即模拟「上游一个字都没返回」。"""

    def __init__(self, chunks):
        self.chunks = chunks

    def get_current_model_name(self):
        return "local"

    async def stream_chat(self, **kwargs):
        for chunk in self.chunks:
            yield chunk


class DummyAgent:
    def __init__(self, llm):
        self.is_initialized = True
        self.llm_module = llm
        self.dependency_manager = None
        self.tool_registry = DummyToolRegistry()
        self.emotion_manager = DummyEmotionManager()
        self.config = SimpleNamespace(temperature=0.1)

    async def initialize(self):
        self.is_initialized = True

    async def _build_conversation_history(self, user_id, message, model_hint=None, **kwargs):
        return [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": str(message)},
        ]

    async def _check_daily_routine(self, user_id):
        return None

    async def _save_conversation_history(self, **kwargs):
        return None


def _patch_light_dependencies():
    from core.agents.chat_agent_components import streaming as sm
    import core.services.journal.service as journal_module
    import core.services.active_care.shared.reminder_injection as reminder_module

    async def fake_detect_sensitive_mode(*args, **kwargs):
        return False

    sm.StreamContextBuilder.detect_sensitive_mode = staticmethod(fake_detect_sensitive_mode)
    sm.StreamContextBuilder.detect_wants_long = staticmethod(lambda msg: False)

    async def fake_process_all(*args, **kwargs):
        return {
            "life_stats": {},
            "sensory_feedback": None,
            "behavior_chain": None,
            "dep_result": {"new_unlocks": []},
            "triggered_defects": [],
        }

    sm.ParallelProcessor.process_all = staticmethod(fake_process_all)

    async def _none(*args, **kwargs):
        return None

    journal_module.get_journal_service = lambda: SimpleNamespace(
        get_tomorrow_tone=_none,
        get_plan=_none,
        format_plan_for_injection=lambda plan: "",
    )

    class _EmptyStore:
        async def get_and_clear(self):
            return None

    reminder_module.get_reminder_injection_store = lambda: _EmptyStore()


# ---------------------------------------------------------------- 各项校验


def verify_error_chunk_recognition():
    from core.agents.chat_agent_components.streaming_pipeline.tag_stream_parser import (
        _extract_stream_error,
    )

    print("\n[1/6] provider 错误 chunk 识别")
    cases = [
        ({"error": "Stream Request Failed: "}, "siliconflow 异常"),
        ({"error": "HTTP 503: busy"}, "HTTP 非 200"),
        ({"type": "error", "message": "模型不可用"}, "type=error"),
        ({"status": "error", "error": "boom", "error_code": "E_X"}, "status=error"),
    ]
    for chunk, desc in cases:
        msg, code = _extract_stream_error(chunk)
        check(bool(msg), f"{desc} 被识别为错误（msg={msg!r}, code={code}）")

    for normal in ({"content": "你好"}, {"reasoning": "思考"}, {"done": True}):
        msg, _ = _extract_stream_error(normal)
        check(msg is None, f"正常 chunk {normal} 不误判")


def verify_session_raises():
    from core.agents.chat_agent_components.streaming_pipeline import (
        LLMStreamError,
        StreamTagSession,
    )

    print("\n[2/6] process_chunk 遇到错误 chunk 必须抛出（不能吞掉）")
    session = StreamTagSession(
        agent=None,
        user_id="verify",
        is_sensitive_mode=False,
        messages=[],
        model_path="local",
    )
    try:
        asyncio.run(session.process_chunk({"error": "Stream Request Failed: "}))
    except LLMStreamError as exc:
        check(exc.error_code == "UPSTREAM_LLM_ERROR", f"异常携带错误码（{exc.error_code}）")
    else:
        check(False, "错误 chunk 被静默忽略（预期抛 LLMStreamError）")


async def _collect_impl(chunks):
    from core.agents.chat_agent_components.streaming import stream_chat_impl

    events = []
    async for evt in stream_chat_impl(
        DummyAgent(FixedLLM(chunks)),
        user_id="verify_upstream_error",
        message="测试",
        save_history=False,
        model_hint="local",
    ):
        events.append(evt)
    return events


def verify_impl_upstream_error():
    print("\n[3/6] stream_chat_impl：上游错误 -> type=error")
    events = asyncio.run(_collect_impl([{"error": "Stream Request Failed: "}]))
    errors = [e for e in events if isinstance(e, dict) and e.get("type") == "error"]
    check(len(errors) == 1, f"产出且仅产出一条 error（实际 {len(errors)}）")
    if errors:
        err = errors[0]
        check(err.get("error_code") == "UPSTREAM_LLM_ERROR", "错误码为 UPSTREAM_LLM_ERROR")
        check("不可用" in str(err.get("message") or ""), f"message 为友好文案（{err.get('message')!r}）")
        check(bool(err.get("done")), "错误事件带 done=True")


def verify_impl_empty_response():
    print("\n[4/6] stream_chat_impl：零输出 -> EMPTY_RESPONSE 而不是静默 done")
    events = asyncio.run(_collect_impl([]))
    errors = [e for e in events if isinstance(e, dict) and e.get("type") == "error"]
    check(len(errors) == 1, f"产出且仅产出一条 error（实际 {len(errors)}）")
    if errors:
        check(errors[0].get("error_code") == "EMPTY_RESPONSE", "错误码为 EMPTY_RESPONSE")


def verify_ws_error_frame():
    from core.interfaces.websocket.adapters.streaming import StreamingHandler

    print("\n[5/6] WebSocket 错误帧为 type=error（含 error_code/content）")

    class FakeWS:
        def __init__(self):
            self.sent = []

        async def send_json(self, payload):
            self.sent.append(payload)

    ws = FakeWS()
    handler = StreamingHandler(adapter=None)
    asyncio.run(
        handler._send_error(
            ws, "AI 服务暂时不可用，请稍后重试", "m1", "c1", "r1",
            error_code="UPSTREAM_LLM_ERROR",
        )
    )
    payload = ws.sent[0] if ws.sent else {}
    check(payload.get("type") == "error", "type=error（不再伪装成普通回复）")
    check(payload.get("error_code") == "UPSTREAM_LLM_ERROR", "带 error_code")
    check(payload.get("message") == payload.get("content"), "message/content 一致（兼容 iOS）")
    json.dumps(payload, ensure_ascii=False)

    from core.interfaces.websocket.adapters.handlers.chat.streaming import _error_payload

    quick = _error_payload(
        "响应超时，请重试",
        msg_id="m2",
        conversation_id="c2",
        request_id="r2",
        error_code="CHAT_TIMEOUT",
    )
    check(quick.get("type") == "error" and quick.get("error_code") == "CHAT_TIMEOUT", "超时兜底也是 type=error")


def verify_clients_static():
    print("\n[6/6] 客户端解析静态核对")
    android_ws = (
        ROOT
        / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"
        / "data/remote/api/WebSocketManager.kt"
    ).read_text(encoding="utf-8")
    check('json.optString("error_code")' in android_ws, "Android 读取 error_code")
    check('"error" -> WebSocketMessage.Error(' in android_ws, "Android 识别 type=error")

    observer = (
        ROOT
        / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"
        / "presentation/chat/ChatSessionObserver.kt"
    ).read_text(encoding="utf-8")
    check("isBackendError" in observer, "Android 区分业务错误与传输抖动")

    web = (ROOT / "clients/frontend/aveline-web/src/hooks/wsMessageHandler.ts").read_text(
        encoding="utf-8"
    )
    check("msg.type === 'error'" in web, "Web 收到 type=error 会展示提示")

    ios = (ROOT / "clients/frontend/aveline-ios/Aveline/Core/Network/WebSocketManager.swift").read_text(
        encoding="utf-8"
    )
    check('case "error":' in ios, "iOS 有 error 分支")


def main():
    _patch_light_dependencies()
    verify_error_chunk_recognition()
    verify_session_raises()
    verify_impl_upstream_error()
    verify_impl_empty_response()
    verify_ws_error_frame()
    verify_clients_static()

    print("\n" + "=" * 60)
    if FAILED:
        print(f"FAIL: {len(FAILED)} 项未通过")
        for item in FAILED:
            print(f"  - {item}")
        return 1
    print("PASS: 上游流式失败会以 type=error 送达前端")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
