#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主动关怀决策模型引擎单测。

覆盖三块：精编 state 构造、Decisions API 响应解析、影子模式的容错与阈值口径。
全部走假客户端，不发真实网络请求。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from core.llm.decisions.client import (
    DecisionResult,
    DecisionsClient,
)
from core.services.active_care.decision.engine import (
    build_compact_state,
    maybe_run_decision_shadow,
    run_decision_shadow,
)


def _sample_ctx() -> Dict[str, Any]:
    """构造一份贴近线上 llm_ctx 的样本。"""
    return {
        "now": "2026-10-13 15:00",
        "tod": "工作日下午",
        "chosen_action": "user_health_reminder",
        "time_since_last_interaction": "2小时",
        "elapsed_seconds": 7080,
        "time_since_last_proactive_send": "40分钟",
        "elapsed_since_last_proactive_seconds": 2400,
        "quiet_mode_active": False,
        "sleep_session": False,
        "sleep_status_desc": "用户醒着",
        "priority_focus": {"portrait_priority": ["这周要交报告"]},
        "user_activity": {"process": "workbuddyai.exe", "busy": False},
        "recent_history_summary": ["assistant: 早安", "user: 下午三点提醒我吃药"],
    }


# ============================== 精编 state ==============================


def test_compact_state_keeps_key_facts_and_drops_noise():
    """state 应保留关键事实，且不把原始冷却数字丢给模型比较。"""
    state = build_compact_state(
        _sample_ctx(),
        persona_name="Aveline",
        extra_facts={"到期提醒": "用户要求的三点吃药提醒已到期"},
    )
    assert "Aveline" in state
    assert "2026-10-13 15:00" in state
    assert "下午三点提醒我吃药" in state
    assert "用户要求的三点吃药提醒已到期" in state
    assert "user_health_reminder" in state
    # 原始秒数不得出现在 state 里（冷却余量这类算术应由代码判断）
    assert "2400" not in state
    assert "7080" not in state


def test_compact_state_is_compact():
    """精编 state 必须显著短于线上 9k 字符的上下文 dump。"""
    state = build_compact_state(_sample_ctx(), persona_name="Aveline")
    assert len(state) < 600


def test_compact_state_respects_max_chars():
    """超出上限时按行截断，不产生半行。"""
    ctx = _sample_ctx()
    ctx["priority_focus"] = {"portrait_priority": [f"话题{i}" for i in range(50)]}
    state = build_compact_state(ctx, persona_name="Aveline", max_chars=120)
    assert len(state) <= 120
    for line in state.splitlines():
        assert line.strip()


def test_compact_state_handles_empty_ctx():
    """空上下文不应抛异常，且仍给出最小可用骨架。"""
    state = build_compact_state({}, persona_name="Aveline")
    assert "Aveline" in state
    assert state.strip()


def test_compact_state_skips_blank_extra_facts():
    """补充事实为空时不应产生空行。"""
    state = build_compact_state(
        _sample_ctx(), persona_name="Aveline", extra_facts={"到期提醒": ""}
    )
    assert "到期提醒" not in state


# ============================== 影子模式 ==============================


class _FakeClient:
    """假客户端：返回预设结果，或抛预设异常。"""

    def __init__(self, result: Optional[DecisionResult] = None, exc: Optional[Exception] = None):
        self.api_key = "fake"
        self._result = result
        self._exc = exc
        self.closed = False

    async def decide(self, **kwargs) -> Optional[DecisionResult]:
        if self._exc is not None:
            raise self._exc
        return self._result

    async def close(self) -> None:
        self.closed = True


def _patch_client(monkeypatch, client) -> None:
    """把影子模块里的客户端工厂替换成假客户端。"""
    from core.services.active_care.decision.engine import shadow as shadow_module

    monkeypatch.setattr(shadow_module, "resolve_decisions_client", lambda **_: client)


@pytest.mark.asyncio
async def test_shadow_threshold_maps_noul_to_send(monkeypatch):
    """noul >= 阈值判为「值得发」，低于阈值判为延后。"""
    body = (
        '{"answers":{"worth_contacting":{"type":"noul","noul":0.8},'
        '"retry_bucket":{"type":"choice","choice":"900","confidence":0.5}},'
        '"usage":{"input_tokens":100,"output_tokens":0,"cost":1e-05}}'
    )
    result = DecisionsClient._parse_response(body, "m", 500.0)
    client = _FakeClient(result=result)
    _patch_client(monkeypatch, client)

    comparison = await run_decision_shadow(
        llm_ctx=_sample_ctx(),
        chosen_action="user_health_reminder",
        real_action="defer_active_care",
        models=["m"],
        threshold=0.5,
    )
    assert comparison is not None
    verdict = comparison.verdicts[0]
    assert verdict.would_send is True
    assert verdict.noul == pytest.approx(0.8)
    assert verdict.retry_seconds == 900
    assert client.closed is True


@pytest.mark.asyncio
async def test_shadow_below_threshold_is_defer(monkeypatch):
    """低于阈值判为延后。"""
    body = '{"answers":{"worth_contacting":{"type":"noul","noul":0.17}},"usage":{}}'
    result = DecisionsClient._parse_response(body, "m", 10.0)
    _patch_client(monkeypatch, _FakeClient(result=result))

    comparison = await run_decision_shadow(
        llm_ctx=_sample_ctx(),
        chosen_action="a",
        real_action="defer_active_care",
        models=["m"],
        threshold=0.5,
    )
    assert comparison is not None
    assert comparison.verdicts[0].would_send is False


@pytest.mark.asyncio
async def test_shadow_swallows_client_exception(monkeypatch):
    """客户端抛异常时影子模式只记 error，不向上抛。"""
    _patch_client(monkeypatch, _FakeClient(exc=RuntimeError("boom")))

    comparison = await run_decision_shadow(
        llm_ctx=_sample_ctx(),
        chosen_action="a",
        real_action="send_active_care",
        models=["m"],
    )
    assert comparison is not None
    assert comparison.verdicts[0].error.startswith("RuntimeError")
    assert comparison.verdicts[0].would_send is False


@pytest.mark.asyncio
async def test_shadow_records_no_result_as_error(monkeypatch):
    """客户端返回 None 时记为 no_result，而不是当成「不发送」。"""
    _patch_client(monkeypatch, _FakeClient(result=None))

    comparison = await run_decision_shadow(
        llm_ctx=_sample_ctx(), chosen_action="a", real_action="send_active_care", models=["m"]
    )
    assert comparison is not None
    assert comparison.verdicts[0].error == "no_result"


@pytest.mark.asyncio
async def test_maybe_run_shadow_disabled_makes_no_call(monkeypatch):
    """开关关闭时不产生任何调用。"""
    called = {"n": 0}

    async def _boom(**kwargs):
        called["n"] += 1
        return None

    from core.services.active_care.decision import engine as engine_module

    monkeypatch.setattr(engine_module, "run_decision_shadow", _boom)
    monkeypatch.setattr(
        engine_module,
        "get_active_care_config",
        lambda key, default=None, **_: False if "enabled" in key else default,
    )

    out = await maybe_run_decision_shadow(
        llm_ctx=_sample_ctx(), chosen_action="a", result={"action": "defer_active_care"}
    )
    assert out is None
    assert called["n"] == 0


def test_shadow_log_skipped_under_pytest(monkeypatch):
    """单测进程里不得往生产影子日志写 fixture 数据。

    回归点：``run_decision_shadow`` 无条件调 ``_log_comparison``，导致跑一次单测
    就往 ``logs/<日期>/active_care_decision_shadow.log`` 灌几条
    ``chosen_action="a"`` 的假样本，把用户统计一致率用的日志污染掉。
    """
    from core.services.active_care.decision.engine import shadow as shadow_module

    captured = []
    monkeypatch.setattr(
        shadow_module.logger, "info", lambda *args, **kwargs: captured.append(args)
    )
    shadow_module._log_comparison(
        shadow_module.ShadowComparison(
            chosen_action="a",
            real_action="defer_active_care",
            real_reason="",
            state_chars=1,
            state_preview="x",
        ),
        0.5,
    )
    assert captured == []
    assert shadow_module.running_under_pytest() is True


@pytest.mark.asyncio
async def test_maybe_run_shadow_never_raises(monkeypatch):
    """影子链路内部异常不得影响主流程。"""
    from core.services.active_care.decision import engine as engine_module

    async def _boom(**kwargs):
        raise RuntimeError("shadow exploded")

    monkeypatch.setattr(engine_module, "run_decision_shadow", _boom)
    monkeypatch.setattr(
        engine_module,
        "get_active_care_config",
        lambda key, default=None, **_: True if "enabled" in key else default,
    )

    out = await maybe_run_decision_shadow(
        llm_ctx=_sample_ctx(), chosen_action="a", result={"action": "defer_active_care"}
    )
    assert out is None


