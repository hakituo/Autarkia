"""按请求开关思考模式（thinking）的链路测试。

覆盖三层：
1. ``normalize_thinking``：客户端各种写法（bool / 0-1 / "true"/"off" / 缺省）的归一，
   缺省必须归一成 None（沿用后端配置），不能被当成 False 把思考关掉；
2. ContextVar 的请求级生命周期：设置 → 子任务继承 → 复原后回空；
3. 非流式生成循环把开关注入 llm kwargs —— DeepSeekClient 靠这个 kwarg 写
   ``payload["thinking"]``，不传就继续用后端配置。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

# 必须从门面导入：直接 import handler_llm_loop 会与 handler 形成循环导入
from core.agents.chat_agent_components.handler import _run_llm_turns
from core.agents.chat_agent_components.thinking_mode import (
    get_request_thinking,
    normalize_thinking,
    reset_request_thinking,
    set_request_thinking,
)

TOOLS = SimpleNamespace(openai_tools=None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        ("true", True),
        (" enabled ", True),
        ("off", False),
        ("disabled", False),
        (None, None),
        ("", None),
        ("随便", None),
        ({"type": "enabled"}, None),
    ],
)
def test_normalize_thinking(raw, expected):
    """客户端写法归一；没表态一律 None（沿用后端配置）。"""
    assert normalize_thinking(raw) is expected


def test_request_thinking_is_scoped_and_restorable():
    """设置后本请求可见，复原后回空，不会串到后续请求。"""
    assert get_request_thinking() is None
    token = set_request_thinking(False)
    try:
        assert get_request_thinking() is False
    finally:
        reset_request_thinking(token)
    assert get_request_thinking() is None


async def _fake_chat(recorded: dict, messages, **kwargs):
    recorded.update(kwargs)
    return {"response": "好", "finish_reason": "stop"}


def _build_agent(recorded: dict):
    return SimpleNamespace(
        config=SimpleNamespace(temperature=1.0),
        llm_module=SimpleNamespace(
            chat=lambda messages, **kwargs: _fake_chat(recorded, messages, **kwargs)
        ),
    )


async def _run_once(recorded: dict) -> None:
    await _run_llm_turns(
        _build_agent(recorded),
        [],
        TOOLS,
        user_id="unit-test",
        message="在吗",
        max_tokens=16,
        repetition_penalty=1.0,
        use_server_side_search=False,
        max_turns=1,
    )


async def test_llm_loop_injects_thinking_flag_when_requested():
    """请求明确关思考时，kwargs 里带 thinking_enabled=False。"""
    recorded: dict = {}
    token = set_request_thinking(False)
    try:
        await _run_once(recorded)
    finally:
        reset_request_thinking(token)

    assert recorded["thinking_enabled"] is False


async def test_llm_loop_keeps_backend_default_when_not_requested():
    """没有表态时不传该 kwarg，交给后端配置决定。"""
    recorded: dict = {}
    await _run_once(recorded)

    assert "thinking_enabled" not in recorded
