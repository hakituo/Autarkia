"""主动消息 payload 的 profile_filename 归属补齐（单角色模式）。

回归背景：单 persona 模式下 proactive_checker 走 else 分支，profile_filename
恒为空串，payload 既没有 profile_filename 也没有 role_name，客户端无法把
消息归到角色，表现为「有通知、点进去却没有这条消息」。dispatch_message 现在
按当前 runtime scope 反查规范入口文件补进 payload。
"""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest



# ==================== 单角色模式的 payload 归属补齐 ====================
#
# 回归背景：单 persona 模式下 proactive_checker 走 `else: _execute_decision_flow(now)`，
# profile_filename 恒为空串，payload 既没有 profile_filename 也没有 role_name，
# 客户端无法把消息归到角色 → 「有通知、点进去却没有这条消息」。
# dispatch_message 现在按当前 runtime scope 反查规范入口文件补进 payload。


def _dispatcher_stub(runtime_scope="aveline", resolved="", resolve_error=None):
    """造一个只够跑 dispatch_message 的 executor/dispatcher 桩。"""
    from core.services.active_care.core.executor import ActiveCareExecutor
    from core.services.active_care.core.message_dispatcher import MessageDispatcher

    executor = ActiveCareExecutor.__new__(ActiveCareExecutor)
    executor.consecutive_non_responses = {}
    executor.hardware_intent_resolver = SimpleNamespace(
        determine=lambda *_a, **_k: SimpleNamespace(to_dict=lambda: {})
    )
    executor.state_persistence = SimpleNamespace(
        persist_proactive_message=AsyncMock(return_value=None)
    )

    if resolve_error is not None:

        def _raise(_scope):
            raise resolve_error

        resolver = _raise
    else:
        resolver = lambda _scope: resolved  # noqa: E731

    executor.storage = SimpleNamespace(
        increment_proactive_count=AsyncMock(return_value=None),
        get_runtime_scope=lambda: runtime_scope,
        resolve_profile_filename_from_scope=resolver,
    )
    aveline_service = SimpleNamespace(
        dispatch_proactive_message=AsyncMock(return_value={"delivered": True})
    )
    return MessageDispatcher(executor), aveline_service, executor


async def _dispatch(dispatcher, aveline_service, *, profile_filename=None):
    from datetime import datetime

    kwargs = {} if profile_filename is None else {"profile_filename": profile_filename}
    return await dispatcher.dispatch_message(
        aveline_service,
        {"content": "困了，我先继续睡啦", "tts_text": "困了，我先继续睡啦", "message_type": "text"},
        "sleep_again_proactive",
        None,
        "private_10001__persona__core_aveline",
        "private_10001",
        "qq",
        "qq",
        "thought",
        {"proactive_state": {}},
        time.time(),
        datetime.now(),
        **kwargs,
    )


def _extra_payload(aveline_service):
    return aveline_service.dispatch_proactive_message.await_args.kwargs["extra_payload"]


@pytest.mark.asyncio
async def test_single_persona_payload_profile_filename_filled_from_scope():
    """单角色模式（profile_filename 为空）也要把归属字段补进 payload。"""
    dispatcher, service, _ = _dispatcher_stub(
        runtime_scope="aveline", resolved="core_aveline.json"
    )

    assert await _dispatch(dispatcher, service) is True

    extra = _extra_payload(service) or {}
    assert extra.get("profile_filename") == "core_aveline.json"
    assert "role_name" in extra and isinstance(extra["role_name"], str)


@pytest.mark.asyncio
async def test_single_persona_payload_skips_unresolvable_scope():
    """反查不到（隔离 scope / 未登记角色）时 payload 不加字段，绝不猜角色。"""
    dispatcher, service, _ = _dispatcher_stub(
        runtime_scope="persona_deadbeefdeadbeef", resolved=""
    )

    assert await _dispatch(dispatcher, service) is True

    assert _extra_payload(service) is None


@pytest.mark.asyncio
async def test_single_persona_payload_survives_lookup_failure():
    """反查抛异常不能影响投递，payload 退回无归属字段。"""
    dispatcher, service, _ = _dispatcher_stub(
        runtime_scope="aveline", resolve_error=RuntimeError("registry down")
    )

    assert await _dispatch(dispatcher, service) is True

    assert _extra_payload(service) is None


@pytest.mark.asyncio
async def test_explicit_profile_filename_wins_and_skips_lookup():
    """双角色模式传了 profile_filename 时行为不变，且不该再去反查。"""
    dispatcher, service, executor = _dispatcher_stub(
        runtime_scope="aveline", resolved="core_aveline.json"
    )
    calls = []
    executor.storage.resolve_profile_filename_from_scope = lambda scope: calls.append(scope) or ""

    assert await _dispatch(dispatcher, service, profile_filename="core_ling.json") is True

    assert (_extra_payload(service) or {}).get("profile_filename") == "core_ling.json"
    assert calls == []


@pytest.mark.asyncio
async def test_payload_fallback_does_not_leak_into_stale_check():
    """关键回归：补齐只能喂 payload，过期判定必须仍拿到原始的空 profile_filename。

    否则会连带把 per-persona 计数 key 从 "" 换成真实 scope，
    把 non_response 计数迁到另一个 state 文件（属行为变更）。
    """
    dispatcher, service, _ = _dispatcher_stub(
        runtime_scope="aveline", resolved="core_aveline.json"
    )
    seen = {}

    def _capture(**kwargs):
        seen.update(kwargs)
        return None

    dispatcher._get_stale_chat_reason = _capture

    assert await _dispatch(dispatcher, service) is True

    assert seen.get("profile_filename") == ""
    assert (_extra_payload(service) or {}).get("profile_filename") == "core_aveline.json"
