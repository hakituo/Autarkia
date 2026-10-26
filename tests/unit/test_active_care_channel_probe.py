#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户最近活跃端探测单测。

核心回归点（2026-10-16 bug）：用户在 App 聊天时必须判出 ``app`` ——
旧的 ``probe_client_type()`` 只要 QQ 连着就返回 ``qq``，会把 App 误判成 QQ。
"""

from __future__ import annotations

import time
from typing import Any, Dict

import pytest

from core.services.active_care.core.channel_probe import (
    DEFAULT_MAX_AGE_SECONDS,
    detect_user_active_channel,
)


class _FakeStorage:
    """只带 ``_recent_user_message_cache`` 的桩 storage。"""

    def __init__(self, cache: Dict[str, Any] | None = None):
        self._recent_user_message_cache = cache if cache is not None else {}


def _entry(ts: float, content: str = "hi") -> Dict[str, Any]:
    return {"content": content, "timestamp": ts}


# ============================== 基本判定 ==============================


def test_detects_app_when_latest_message_from_app():
    """最近一条来自 App 会话 → app。"""
    now = time.time()
    storage = _FakeStorage(
        {
            "private_10001__core_aveline": _entry(now - 600),
            "web_role_aveline": _entry(now - 30),
        }
    )
    assert detect_user_active_channel(storage) == "app"


def test_detects_qq_when_latest_message_from_qq():
    """最近一条来自 QQ 会话 → qq。"""
    now = time.time()
    storage = _FakeStorage(
        {
            "web_role_aveline": _entry(now - 900),
            "private_10001__core_aveline": _entry(now - 20),
        }
    )
    assert detect_user_active_channel(storage) == "qq"


def test_latest_timestamp_wins_regardless_of_dict_order():
    """判定依据是时间戳而不是插入顺序。"""
    now = time.time()
    storage = _FakeStorage(
        {
            "web_role_ling": _entry(now - 10),
            "private_10001__core_ling": _entry(now - 5000),
        }
    )
    assert detect_user_active_channel(storage) == "app"


# ============================== 保守降级 ==============================


def test_returns_empty_when_signal_expired():
    """信号超过有效期 → 判不出来，返回空串（调用方退回双投）。"""
    now = time.time()
    storage = _FakeStorage({"web_role_aveline": _entry(now - DEFAULT_MAX_AGE_SECONDS - 60)})
    assert detect_user_active_channel(storage) == ""


def test_max_age_can_be_overridden():
    """有效期可注入，便于测试与调参。"""
    now = time.time()
    storage = _FakeStorage({"web_role_aveline": _entry(now - 120)})
    assert detect_user_active_channel(storage, max_age_seconds=60, now_ts=now) == ""
    assert detect_user_active_channel(storage, max_age_seconds=600, now_ts=now) == "app"


def test_returns_empty_for_unknown_namespace():
    """命名空间不认识 → 空串，不猜。"""
    now = time.time()
    storage = _FakeStorage({"default_user": _entry(now)})
    assert detect_user_active_channel(storage) == ""


def test_returns_empty_when_cache_empty():
    """缓存为空 → 空串。"""
    assert detect_user_active_channel(_FakeStorage({})) == ""


def test_ignores_malformed_entries():
    """缓存里混入非法结构时跳过，不抛异常。"""
    now = time.time()
    storage = _FakeStorage(
        {
            "web_role_aveline": "not-a-dict",
            "private_10001": {"content": "x", "timestamp": "not-a-number"},
            "private_10002": _entry(now - 5),
        }
    )
    assert detect_user_active_channel(storage) == "qq"


def test_swallows_internal_exception(monkeypatch):
    """内部异常一律降级为「未知」，绝不影响投递链路。"""

    class _Boom:
        @property
        def _recent_user_message_cache(self):
            raise RuntimeError("boom")

    assert detect_user_active_channel(_Boom()) == ""


def test_resolve_storage_failure_returns_empty(monkeypatch):
    """反查 active care 服务失败时返回空串。"""
    import core.services.active_care.core.service as service_module

    monkeypatch.setattr(service_module, "get_active_care_service", lambda: None)
    assert detect_user_active_channel(None) == ""


@pytest.mark.parametrize("bad_age", ["abc", None])
def test_invalid_max_age_falls_back_to_default(bad_age):
    """非法有效期回退到模块默认值而不是崩掉。"""
    now = time.time()
    storage = _FakeStorage({"web_role_aveline": _entry(now - 10)})
    assert detect_user_active_channel(storage, max_age_seconds=bad_age) == "app"
