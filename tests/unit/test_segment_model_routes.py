"""按角色分 key 的模型路由与回填调度器解析（不联网、不读真实 key 正文）。"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from memory.nightly import model_routes
from scripts.maintenance.segment_backfill import policy
from scripts.maintenance.segment_backfill import scheduler as scheduler_module
from scripts.maintenance.segment_backfill.scheduler import (
    DirectScheduler,
    parse_route,
    resolve_key,
)


def test_deepseek_route_uses_role_key_and_falls_back_to_default():
    assert model_routes.deepseek_key_alias("aveline") == "aveline"
    assert model_routes.deepseek_key_alias("ling") == "ling"
    assert model_routes.deepseek_key_alias("rushuang") == "rushuang"
    assert model_routes.deepseek_key_alias("yeye") == "yeye"
    # ye / tt / lin 没有专属 key：仍走默认 key，前缀照样按角色固定
    assert model_routes.deepseek_key_alias("ye") == ""
    assert model_routes.deepseek_route("aveline") == (
        "cloud:deepseek:aveline:deepseek-v4-flash"
    )
    assert model_routes.deepseek_route("tt") == "cloud:deepseek:deepseek-v4-flash"
    assert model_routes.minimax_route() == "cloud:minimax:plan:MiniMax-M3"


def test_policy_routes_match_provider_choice():
    assert policy.model_route_for("aveline", policy.MINIMAX) == (
        "cloud:minimax:plan:MiniMax-M3"
    )
    assert policy.model_route_for("ling", policy.DEEPSEEK) == (
        "cloud:deepseek:ling:deepseek-v4-flash"
    )
    assert policy.fallback_route_for("aveline") == (
        "cloud:deepseek:aveline:deepseek-v4-flash"
    )
    assert policy.key_alias_for("aveline", policy.MINIMAX) == ""
    assert policy.key_alias_for("rushuang", policy.DEEPSEEK) == "rushuang"


@pytest.mark.parametrize(
    ("hint", "default", "expected"),
    [
        (
            "cloud:deepseek:aveline:deepseek-v4-flash",
            "deepseek",
            ("deepseek", "aveline", "deepseek-v4-flash"),
        ),
        (
            "cloud:deepseek:deepseek-v4-flash",
            "deepseek",
            ("deepseek", "", "deepseek-v4-flash"),
        ),
        (
            "cloud:minimax:plan:MiniMax-M3",
            "minimax",
            ("minimax", "plan", "MiniMax-M3"),
        ),
        ("", "minimax", ("minimax", "", "MiniMax-M3")),
        ("deepseek-v4-flash", "deepseek", ("deepseek", "", "deepseek-v4-flash")),
        (
            "deepseek:aveline:deepseek-v4-flash",
            "deepseek",
            ("deepseek", "aveline", "deepseek-v4-flash"),
        ),
    ],
)
def test_parse_route(hint, default, expected):
    assert parse_route(hint, default) == expected


def test_resolve_key_is_alias_case_insensitive_and_falls_back(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "default-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY_TestRole", "role-key")
    assert resolve_key("deepseek", "testrole") == "role-key"
    assert resolve_key("deepseek", "TESTROLE") == "role-key"
    assert resolve_key("deepseek", "missing") == "default-key"
    monkeypatch.setenv("MINIMAX_PLAN_API_KEY", "plan-key")
    assert resolve_key("minimax", "plan") == "plan-key"


class _Resp:
    def __init__(self, status: int, body: dict):
        self.status_code = status
        self._body = body

    @property
    def text(self) -> str:
        return json.dumps(self._body, ensure_ascii=False)

    def json(self) -> dict:
        return self._body


class _Client:
    def __init__(self, responses: list[_Resp], calls: list[tuple[str, dict]]):
        self._responses = responses
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, url: str, headers: dict, json: dict):
        self._calls.append((url, json))
        return self._responses.pop(0)


def _install_fake_http(monkeypatch, responses: list[_Resp]) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_kwargs: _Client(responses, calls),
    )
    monkeypatch.setattr(
        scheduler_module, "resolve_key", lambda provider, alias: f"{provider}-key"
    )
    return calls


def _run(scheduler: DirectScheduler, hint: str) -> list[str]:
    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in scheduler.submit_llm_task(
                [{"role": "user", "content": "测试"}], model_hint=hint
            )
        ]

    return asyncio.run(collect())


def _reply(content: str = "ok") -> _Resp:
    return _Resp(
        200,
        {
            "base_resp": {"status_code": 0},
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        },
    )


def test_scheduler_switches_to_deepseek_when_minimax_quota_is_exhausted(monkeypatch):
    calls = _install_fake_http(
        monkeypatch,
        [
            _Resp(429, {"base_resp": {"status_code": 1008, "status_msg": "insufficient balance"}}),
            _reply(),
            _reply(),
        ],
    )
    scheduler = DirectScheduler(
        "minimax", quota_fallback="cloud:deepseek:aveline:deepseek-v4-flash"
    )
    hint = "cloud:minimax:plan:MiniMax-M3"

    assert _run(scheduler, hint) == ["ok"]
    assert "minimaxi.com" in calls[0][0]
    assert "deepseek.com" in calls[1][0]
    assert scheduler.usage["quota_switch"] == 1
    assert scheduler.usage["last"]["provider"] == "deepseek"
    assert scheduler.usage["last"]["alias"] == "aveline"

    assert _run(scheduler, hint) == ["ok"]
    assert "deepseek.com" in calls[2][0]


def test_scheduler_handles_minimax_200_quota_error(monkeypatch):
    _install_fake_http(
        monkeypatch,
        [
            _Resp(200, {"base_resp": {"status_code": 1008, "status_msg": "余额不足"}}),
            _reply("切到降级路由"),
        ],
    )
    scheduler = DirectScheduler(
        "minimax", quota_fallback="cloud:deepseek:ling:deepseek-v4-flash"
    )
    assert _run(scheduler, "cloud:minimax:plan:MiniMax-M3") == ["切到降级路由"]
    assert scheduler.quota_exhausted is True


def test_scheduler_retries_transient_429_on_same_provider(monkeypatch):
    async def _no_sleep(*_args):
        return None

    monkeypatch.setattr(scheduler_module.asyncio, "sleep", _no_sleep)
    calls = _install_fake_http(
        monkeypatch,
        [_Resp(429, {"error": {"message": "rate limit exceeded"}}), _reply()],
    )
    scheduler = DirectScheduler(
        "minimax", quota_fallback="cloud:deepseek:aveline:deepseek-v4-flash"
    )
    assert _run(scheduler, "cloud:minimax:plan:MiniMax-M3") == ["ok"]
    assert all("minimaxi.com" in url for url, _payload in calls)
    assert scheduler.usage["quota_switch"] == 0
