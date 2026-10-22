#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主动关怀投递渠道策略。

现状（本模块引入前）：QQ 恒为主渠道（``probe_client_type`` 只要有 QQ 连接就返回
``qq``），App 只要在线就**无条件**再补投一份。用户同时挂着 QQ 和 App 时，同一条
主动消息会在两端各弹一次 —— 这就是「全部发」。

本模块把「发哪一端」从硬编码改成可审计的策略函数：输入是当前可观测的事实
（各端是否在线、触发来自哪一端、消息类型、时段），输出是两端各自的投递开关
与命中规则名，便于在日志里复盘「这条为什么只发了 App」。

模式由 ``life_simulation.active_care_channel_mode`` 控制：

- ``mirror_app``（默认，等于改动前的行为）：QQ 主投，App 在线即补投
- ``prefer_app``：优先只发 App；App 投递失败才回退 QQ
- ``prefer_qq``：只发 QQ，不补投 App
- ``smart``：按下面的规则分流

``smart`` 的规则（自上而下，命中即返回）：

1. 作息/健康类必须两端都发 —— 这类消息用户可能只看一端，宁可重复也不能漏；
2. App 不在线 → 只发 QQ；
3. 用户最近一条消息落在 QQ → 只发 QQ，避免 App 再弹一次；
4. 用户最近一条消息落在 App → 只发 App；
5. 拿不到「用户最近活跃端」（无信号或信号已过期）→ 退回触发端信号兜底，
   仍判不出来就保持双投（沿用旧行为，不擅自减投）。

**「用户最近活跃端」由 `channel_probe.detect_user_active_channel` 提供**，判据是
用户最近一条消息落在哪个会话命名空间 —— **不要用 `probe_client_type()`**：
它只要检测到任意 QQ 连接就返回 ``qq``，回答的是「有哪些连接在」而不是
「用户此刻在哪一端」，实测用户在 App 里聊天时它照样返回 ``qq``。
"""

from dataclasses import dataclass
from typing import Any, Dict, List

# 渠道模式取值
MODE_MIRROR_APP = "mirror_app"
MODE_PREFER_APP = "prefer_app"
MODE_PREFER_QQ = "prefer_qq"
MODE_SMART = "smart"

VALID_MODES = (MODE_MIRROR_APP, MODE_PREFER_APP, MODE_PREFER_QQ, MODE_SMART)

# 作息 / 健康类：用户可能只看一端，必须两端都发
_ALWAYS_BOTH_TYPES = frozenset(
    {
        "user_health_reminder",
        "good_morning_proactive",
        "goodnight_proactive",
    }
)

# 触发端归一化：QQ 侧的各种写法都算 qq
_QQ_CLIENT_TYPES = frozenset({"qq", "qq_official", "napcat"})

# 会话 id 命名空间 → 投递端。实测取值（2026-10-16 日志）：
#   App/Web：web_role_aveline、web_role_ling
#   QQ 传输端：private_10001__core_aveline、private_123456789、
#             shared__persona__core_aveline、shared__scope__aveline
# 用命名空间而不是 probe_client_type()：后者只要检测到任意 QQ 连接就返回 qq，
# 回答的是「有哪些连接在」，不是「用户此刻在哪一端」。
_APP_CID_PREFIXES = ("web_", "web_role_", "app_")
_TRANSPORT_CID_PREFIXES = (
    "private_",
    "group_",
    "shared__",
    "peer_",
    "tg_",
    "telegram_group_",
    "telegram_private_",
)

CHANNEL_APP = "app"
CHANNEL_QQ = "qq"


def classify_conversation_channel(conversation_id: str) -> str:
    """按会话 id 命名空间判断它属于哪一端。

    Args:
        conversation_id: 会话 id。

    Returns:
        ``"app"`` / ``"qq"``；命名空间不认识时返回空串（调用方按「未知」处理）。
    """
    cid = str(conversation_id or "").strip().lower()
    if not cid:
        return ""
    if cid.startswith(_APP_CID_PREFIXES):
        return CHANNEL_APP
    if cid.startswith(_TRANSPORT_CID_PREFIXES):
        return CHANNEL_QQ
    return ""


@dataclass(frozen=True)
class ChannelDecision:
    """一次投递的渠道决策。"""

    deliver_qq: bool
    deliver_app: bool
    mode: str
    rule: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "deliver_qq": self.deliver_qq,
            "deliver_app": self.deliver_app,
            "mode": self.mode,
            "rule": self.rule,
        }

    def describe(self) -> str:
        """一行可读描述，直接进日志。"""
        channels = []
        if self.deliver_qq:
            channels.append("QQ")
        if self.deliver_app:
            channels.append("App")
        return f"{'+'.join(channels) or '不投递'}({self.mode}/{self.rule})"


def _normalize_mode(raw: Any) -> str:
    """把配置值归一化成合法模式，非法值回退到保持现状的 mirror_app。"""
    mode = str(raw or "").strip().lower()
    return mode if mode in VALID_MODES else MODE_MIRROR_APP


def _is_qq_origin(requested_client_type: str) -> bool:
    """触发是否来自 QQ 侧。"""
    return str(requested_client_type or "").strip().lower() in _QQ_CLIENT_TYPES


def resolve_channel_mode() -> str:
    """读取渠道模式配置；读取失败时回退到 mirror_app（等于旧行为）。"""
    try:
        from core.utils.config_accessor import get_active_care_config

        return _normalize_mode(
            get_active_care_config("active_care_channel_mode", default=MODE_MIRROR_APP)
        )
    except Exception:  # noqa: BLE001 - 配置缺失不应阻断投递
        return MODE_MIRROR_APP


def decide_channel(
    *,
    sys_prompt_type: str = "",
    app_online: bool,
    requested_client_type: str = "",
    user_active_channel: str = "",
    mode: str = "",
) -> ChannelDecision:
    """决定本次主动消息投递到哪一端。

    Args:
        sys_prompt_type: 消息类型（如 user_health_reminder / curious_question）。
        app_online: 当前是否有在线的 App/Web 客户端可补投。
        requested_client_type: 触发本次消息的客户端类型（qq / websocket / web）。
            只作**兜底**信号：``probe_client_type()`` 只要检测到任意 QQ 连接就返回 qq，
            无法反映用户此刻在哪一端。
        user_active_channel: 「用户最近一条消息落在哪一端」，取值 ``"app"`` / ``"qq"`` /
            空串（未知）。由 ``channel_probe.detect_user_active_channel`` 提供，
            是 smart 模式的主判据。
        mode: 渠道模式；留空时读配置。

    Returns:
        ChannelDecision；调用方据此决定是否补投 App、是否跳过 QQ 主投。
    """
    resolved_mode = _normalize_mode(mode) if mode else resolve_channel_mode()
    prompt_type = str(sys_prompt_type or "").strip().lower()

    if resolved_mode == MODE_PREFER_QQ:
        return ChannelDecision(True, False, resolved_mode, "prefer_qq")
    if resolved_mode == MODE_PREFER_APP:
        return ChannelDecision(not app_online, app_online, resolved_mode, "prefer_app")
    if resolved_mode == MODE_MIRROR_APP:
        return ChannelDecision(True, bool(app_online), resolved_mode, "mirror_app")

    # ---- smart：按规则分流 ----
    # 规则顺序：作息/健康类必须双发 → App 离线只能走 QQ →
    #          用户最近在哪一端就只发哪一端 → 判不出来就保持双发（不擅自减投）。
    if prompt_type in _ALWAYS_BOTH_TYPES:
        return ChannelDecision(True, True, resolved_mode, "always_both")
    if not app_online:
        return ChannelDecision(True, False, resolved_mode, "app_offline")

    active = str(user_active_channel or "").strip().lower()
    if active == CHANNEL_QQ:
        return ChannelDecision(True, False, resolved_mode, "user_on_qq")
    if active == CHANNEL_APP:
        return ChannelDecision(False, True, resolved_mode, "user_on_app")

    # 没有「用户最近活跃端」信号时，退回旧的触发端信号兜底
    if _is_qq_origin(requested_client_type):
        return ChannelDecision(True, False, resolved_mode, "trigger_on_qq")
    if str(requested_client_type or "").strip():
        return ChannelDecision(False, True, resolved_mode, "trigger_on_app")
    return ChannelDecision(True, True, resolved_mode, "origin_unknown")


def summarize_decisions(decisions: List[ChannelDecision]) -> Dict[str, int]:
    """统计一组决策命中的规则分布，供验证脚本与复盘使用。"""
    summary: Dict[str, int] = {}
    for decision in decisions:
        summary[decision.rule] = summary.get(decision.rule, 0) + 1
    return summary


__all__ = [
    "CHANNEL_APP",
    "CHANNEL_QQ",
    "MODE_MIRROR_APP",
    "MODE_PREFER_APP",
    "MODE_PREFER_QQ",
    "MODE_SMART",
    "VALID_MODES",
    "ChannelDecision",
    "classify_conversation_channel",
    "decide_channel",
    "resolve_channel_mode",
    "summarize_decisions",
]
