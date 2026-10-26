#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主动关怀投递渠道策略单测。

覆盖四种模式的分流结果、非法模式回退、以及 smart 规则表的命中优先级。
全部为纯函数调用，不依赖 WebSocket / 配置系统。
"""

from __future__ import annotations

import pytest

from core.services.active_care.core.channel_policy import (
    CHANNEL_APP,
    CHANNEL_QQ,
    MODE_MIRROR_APP,
    MODE_PREFER_APP,
    MODE_PREFER_QQ,
    MODE_SMART,
    VALID_MODES,
    ChannelDecision,
    classify_conversation_channel,
    decide_channel,
    summarize_decisions,
)


# ============================== 模式基本行为 ==============================


def test_mirror_app_matches_legacy_behaviour():
    """mirror_app 等于改动前的行为：QQ 恒发，App 在线即补投。"""
    online = decide_channel(app_online=True, mode=MODE_MIRROR_APP)
    assert (online.deliver_qq, online.deliver_app) == (True, True)

    offline = decide_channel(app_online=False, mode=MODE_MIRROR_APP)
    assert (offline.deliver_qq, offline.deliver_app) == (True, False)


def test_prefer_qq_never_mirrors_to_app():
    """prefer_qq 只发 QQ，即使 App 在线也不补投。"""
    decision = decide_channel(app_online=True, mode=MODE_PREFER_QQ)
    assert decision.deliver_qq is True
    assert decision.deliver_app is False


def test_prefer_app_sends_only_app_when_online():
    """prefer_app 在 App 在线时只发 App。"""
    decision = decide_channel(app_online=True, mode=MODE_PREFER_APP)
    assert decision.deliver_qq is False
    assert decision.deliver_app is True


def test_prefer_app_falls_back_to_qq_when_offline():
    """prefer_app 在 App 离线时必须回退 QQ，不能把消息丢掉。"""
    decision = decide_channel(app_online=False, mode=MODE_PREFER_APP)
    assert decision.deliver_qq is True
    assert decision.deliver_app is False


# ============================== smart 规则 ==============================


@pytest.mark.parametrize(
    "prompt_type",
    ["user_health_reminder", "good_morning_proactive", "goodnight_proactive"],
)
def test_smart_always_sends_both_for_routine_types(prompt_type):
    """作息/健康类必须两端都发，即使触发端明确。"""
    decision = decide_channel(
        sys_prompt_type=prompt_type,
        app_online=True,
        requested_client_type="qq",
        mode=MODE_SMART,
    )
    assert (decision.deliver_qq, decision.deliver_app) == (True, True)
    assert decision.rule == "always_both"


def test_smart_app_offline_goes_qq_only():
    """App 不在线时只发 QQ。"""
    decision = decide_channel(
        sys_prompt_type="curious_question",
        app_online=False,
        requested_client_type="qq",
        mode=MODE_SMART,
    )
    assert (decision.deliver_qq, decision.deliver_app) == (True, False)
    assert decision.rule == "app_offline"


def test_smart_user_on_qq_does_not_mirror_to_app():
    """用户在 QQ 时不再往 App 补投，避免两端各弹一次。"""
    decision = decide_channel(
        sys_prompt_type="curious_question",
        app_online=True,
        user_active_channel="qq",
        mode=MODE_SMART,
    )
    assert (decision.deliver_qq, decision.deliver_app) == (True, False)
    assert decision.rule == "user_on_qq"


def test_smart_user_on_app_sends_app_only():
    """用户在 App 时只发 App。"""
    decision = decide_channel(
        sys_prompt_type="curious_question",
        app_online=True,
        user_active_channel="app",
        mode=MODE_SMART,
    )
    assert (decision.deliver_qq, decision.deliver_app) == (False, True)
    assert decision.rule == "user_on_app"


def test_user_active_channel_wins_over_trigger_client_type():
    """「用户最近活跃端」优先于触发端信号。

    这是 2026-10-16 那个 bug 的回归用例：用户在 App 聊天，但触发端
    （probe_client_type）因为 QQ 连着而返回 qq，旧逻辑会误判成只发 QQ。
    """
    decision = decide_channel(
        sys_prompt_type="curious_question",
        app_online=True,
        requested_client_type="qq",
        user_active_channel="app",
        mode=MODE_SMART,
    )
    assert (decision.deliver_qq, decision.deliver_app) == (False, True)
    assert decision.rule == "user_on_app"


def test_smart_falls_back_to_trigger_when_active_channel_unknown():
    """拿不到「用户最近活跃端」时退回触发端信号兜底。"""
    decision = decide_channel(
        sys_prompt_type="curious_question",
        app_online=True,
        requested_client_type="qq",
        user_active_channel="",
        mode=MODE_SMART,
    )
    assert (decision.deliver_qq, decision.deliver_app) == (True, False)
    assert decision.rule == "trigger_on_qq"


def test_smart_unknown_active_channel_and_unknown_trigger_keeps_double_send():
    """两个信号都没有时不擅自减投。"""
    decision = decide_channel(
        sys_prompt_type="curious_question",
        app_online=True,
        requested_client_type="",
        user_active_channel="",
        mode=MODE_SMART,
    )
    assert (decision.deliver_qq, decision.deliver_app) == (True, True)
    assert decision.rule == "origin_unknown"


def test_routine_type_still_double_sends_even_when_user_on_app():
    """作息/健康类优先级最高：即使用户在 App 也两端都发。"""
    decision = decide_channel(
        sys_prompt_type="goodnight_proactive",
        app_online=True,
        user_active_channel="app",
        mode=MODE_SMART,
    )
    assert (decision.deliver_qq, decision.deliver_app) == (True, True)
    assert decision.rule == "always_both"


# ============================== 配置与边界 ==============================


def test_invalid_mode_falls_back_to_mirror_app():
    """非法模式值回退到保持现状的 mirror_app。"""
    decision = decide_channel(app_online=True, mode="not-a-mode")
    assert decision.mode == MODE_MIRROR_APP
    assert (decision.deliver_qq, decision.deliver_app) == (True, True)


def test_mode_is_case_insensitive():
    """模式值大小写不敏感。"""
    decision = decide_channel(app_online=True, mode="SMART")
    assert decision.mode == MODE_SMART


def test_all_modes_declared_in_valid_modes():
    """四个模式都在 VALID_MODES 中，避免漏登记导致静默回退。"""
    assert set(VALID_MODES) == {
        MODE_MIRROR_APP,
        MODE_PREFER_APP,
        MODE_PREFER_QQ,
        MODE_SMART,
    }


def test_every_mode_always_delivers_somewhere():
    """任何模式下都不能出现「两端都不投递」——那等于静默丢消息。"""
    for mode in VALID_MODES:
        for app_online in (True, False):
            for origin in ("", "qq", "websocket"):
                for active in ("", "app", "qq"):
                    decision = decide_channel(
                        sys_prompt_type="curious_question",
                        app_online=app_online,
                        requested_client_type=origin,
                        user_active_channel=active,
                        mode=mode,
                    )
                    assert decision.deliver_qq or decision.deliver_app, (
                        mode,
                        app_online,
                        origin,
                        active,
                    )


# ============================== 会话命名空间判定 ==============================


@pytest.mark.parametrize(
    "cid",
    ["web_role_aveline", "web_role_ling", "web_abc", "app_user"],
)
def test_classify_app_namespaces(cid):
    """App / Web 侧命名空间判为 app。"""
    assert classify_conversation_channel(cid) == CHANNEL_APP


@pytest.mark.parametrize(
    "cid",
    [
        "private_10001__core_aveline",
        "private_123456789",
        "shared__persona__core_aveline",
        "shared__scope__aveline",
        "group_123",
        "peer_core_ling",
        "telegram_private_9",
    ],
)
def test_classify_transport_namespaces(cid):
    """QQ 等 bot 传输端命名空间判为 qq。"""
    assert classify_conversation_channel(cid) == CHANNEL_QQ


@pytest.mark.parametrize("cid", ["", "   ", "default", "default_user", "u"])
def test_classify_unknown_namespaces(cid):
    """不认识的命名空间返回空串，由调用方按「未知」处理（退回双投）。"""
    assert classify_conversation_channel(cid) == ""


def test_classify_is_case_insensitive():
    """命名空间判定不区分大小写。"""
    assert classify_conversation_channel("WEB_ROLE_AVELINE") == CHANNEL_APP
    assert classify_conversation_channel("Private_10001") == CHANNEL_QQ


def test_describe_is_readable():
    """describe() 输出可直接进日志。"""
    decision = ChannelDecision(True, False, MODE_SMART, "user_on_qq")
    assert "QQ" in decision.describe()
    assert "smart" in decision.describe()
    assert decision.as_dict()["rule"] == "user_on_qq"


def test_summarize_decisions_counts_rules():
    """规则命中统计用于复盘分流分布。"""
    decisions = [
        decide_channel(app_online=True, mode=MODE_MIRROR_APP),
        decide_channel(app_online=True, mode=MODE_MIRROR_APP),
        decide_channel(app_online=False, mode=MODE_MIRROR_APP),
    ]
    assert summarize_decisions(decisions) == {"mirror_app": 3}
