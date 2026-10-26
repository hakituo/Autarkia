# -*- coding: utf-8 -*-
"""MiniMax M Plan 订阅 Key 的配置与路由单元测试。

订阅 Key（sk-cp-）与按量付费 Key 不可混用，必须独立成 ``minimax`` 的
``plan`` 别名，模型路径形如 ``cloud:minimax:plan:MiniMax-M3.1-Flash``。
"""

from __future__ import annotations

from config.settings_model import (
    MINIMAX_PLAN_BASE_URL,
    MINIMAX_PLAN_DEFAULT_MODELS,
    MINIMAX_PLAN_KEY_ENV,
    _load_cloud_provider_keys_from_env,
)


def test_plan_alias_is_loaded_from_env(monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_PLAN_BASE_URL", raising=False)
    monkeypatch.setenv(MINIMAX_PLAN_KEY_ENV, "sk-cp-unit-test")

    keys = _load_cloud_provider_keys_from_env()
    plan = keys["minimax"]["plan"]

    assert plan.key_alias == "plan"
    assert plan.api_key == "sk-cp-unit-test"
    assert plan.api_key_env == MINIMAX_PLAN_KEY_ENV
    assert plan.base_url == MINIMAX_PLAN_BASE_URL
    assert plan.models == MINIMAX_PLAN_DEFAULT_MODELS
    assert "MiniMax-M3.1-Flash" in plan.models
    assert "MiniMax-M3" in plan.models


def test_plan_base_url_can_be_overridden(monkeypatch):
    monkeypatch.setenv(MINIMAX_PLAN_KEY_ENV, "sk-cp-unit-test")
    monkeypatch.setenv("MINIMAX_PLAN_BASE_URL", "https://example.com/v1/chat/completions")

    plan = _load_cloud_provider_keys_from_env()["minimax"]["plan"]
    assert plan.base_url == "https://example.com/v1/chat/completions"


def test_no_plan_alias_without_env(monkeypatch):
    monkeypatch.delenv(MINIMAX_PLAN_KEY_ENV, raising=False)

    keys = _load_cloud_provider_keys_from_env()
    assert "plan" not in (keys.get("minimax") or {})


def test_router_resolves_plan_alias():
    """``cloud:minimax:plan:<model>`` 必须命中 plan 客户端而不是 default。"""
    from core.llm.cloud_router import CloudRouterLLMModule

    class _MockClient:
        def get_status(self):
            return {"ok": True}

    plan_client = _MockClient()
    default_client = _MockClient()
    router = CloudRouterLLMModule(
        {"minimax:plan": plan_client, "minimax": default_client},
        default_provider="minimax",
    )

    client, kwargs = router._select_client("cloud:minimax:plan:MiniMax-M3.1-Flash", {})

    assert client is plan_client
    assert kwargs.get("model") == "MiniMax-M3.1-Flash"
