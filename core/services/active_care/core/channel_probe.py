#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户最近活跃端探测（App / QQ）。

**为什么需要它**：渠道策略要判断「用户此刻在哪一端」，但项目里既有的
``core/utils/client_utils.probe_client_type()`` 回答的不是这个问题 ——
它的逻辑是「只要检测到任意 QQ 连接就返回 qq」（注释写着「优先返回 QQ」），
所以用户在 App 里聊天时它照样返回 ``qq``。

实测（2026-10-16 18:00）：用户在 App 的 ``web_role_aveline`` 里说话，
``probe_client_type()`` 仍返回 ``qq``，于是渠道策略把「用户在 App」误判成
「用户在 QQ」。若直接切到 smart 模式，主动消息会**只发 QQ、App 一条都收不到**。

**本模块的判据**：会话 id 的命名空间天然区分端，且用户消息会带会话 id 进
``ActiveCareContext._recent_user_message_cache``（App 与 QQ 两条路径都会写：
``core/services/aveline/stream_orchestrator.py`` 与
``core/interfaces/websocket/adapters/handlers/chat/active_care.py``）。
所以「最近一条用户消息落在哪个命名空间」就能回答「用户此刻在哪一端」。

**保守原则**：拿不到信号、信号已过期、或命名空间不认识时一律返回空串，
让渠道策略退回旧行为（双投）—— 宁可重复一次，也不能因为猜错端而漏消息。
"""

import time
from typing import Any, Dict, Optional

from core.services.active_care.core.channel_policy import classify_conversation_channel
from core.utils.logger import get_logger

logger = get_logger("ACTIVE_CARE_CHANNEL_PROBE")

# 「用户最近活跃端」的有效期。超过这个时长就不再认为「用户还在那一端」，
# 退回双投。默认 1 小时：主动关怀的触发间隔通常是分钟级，
# 一小时内的信号足以判定用户此刻挂着哪一端。
DEFAULT_MAX_AGE_SECONDS = 3600.0


def _resolve_storage(storage: Any = None) -> Optional[Any]:
    """取 ActiveCareStorage；传入优先，否则从活动关怀服务反查。"""
    if storage is not None:
        return storage
    try:
        from core.services.active_care.core.service import get_active_care_service

        service = get_active_care_service()
        if service is None:
            return None
        return getattr(service, "storage", None) or getattr(
            getattr(service, "context", None), "storage", None
        )
    except Exception as exc:  # noqa: BLE001 - 探测失败不应影响投递
        logger.debug("解析 active care storage 失败: %s", exc)
        return None


def _resolve_max_age(max_age_seconds: Optional[float]) -> float:
    """取有效期配置；参数优先，其次配置项，最后模块默认值。"""
    if max_age_seconds is not None:
        try:
            return float(max_age_seconds)
        except (TypeError, ValueError):
            return DEFAULT_MAX_AGE_SECONDS
    try:
        from core.utils.config_accessor import get_active_care_config

        raw = get_active_care_config(
            "active_care_channel_probe_max_age_seconds", default=None
        )
        if raw is not None:
            return float(raw)
    except Exception:  # noqa: BLE001 - 配置缺失回退默认值
        pass
    return DEFAULT_MAX_AGE_SECONDS


def _read_recent_cache(storage: Any) -> Dict[str, Any]:
    """读最近用户消息缓存；结构不符时返回空字典。"""
    cache = getattr(storage, "_recent_user_message_cache", None)
    if isinstance(cache, dict):
        return cache
    return {}


def _pick_latest(cache: Dict[str, Any]) -> Optional[tuple]:
    """从缓存里挑出时间戳最大的一条，返回 (cid, timestamp)。"""
    latest_cid = ""
    latest_ts = 0.0
    for cid, payload in cache.items():
        if not isinstance(payload, dict):
            continue
        try:
            ts = float(payload.get("timestamp") or 0.0)
        except (TypeError, ValueError):
            continue
        if ts > latest_ts:
            latest_ts = ts
            latest_cid = str(cid or "")
    if not latest_cid or latest_ts <= 0:
        return None
    return latest_cid, latest_ts


def detect_user_active_channel(
    storage: Any = None,
    *,
    max_age_seconds: Optional[float] = None,
    now_ts: Optional[float] = None,
) -> str:
    """判断用户最近一条消息落在哪一端。

    Args:
        storage: ActiveCareStorage；留空时自动从活动关怀服务反查。
        max_age_seconds: 信号有效期（秒）；留空时读配置，再退到 1 小时。
        now_ts: 当前时间戳；仅供测试注入。

    Returns:
        ``"app"`` / ``"qq"``；拿不到有效信号时返回空串。
    """
    try:
        resolved_storage = _resolve_storage(storage)
        if resolved_storage is None:
            return ""
        cache = _read_recent_cache(resolved_storage)
        if not cache:
            return ""
        latest = _pick_latest(cache)
        if latest is None:
            return ""
        cid, ts = latest

        max_age = _resolve_max_age(max_age_seconds)
        current = float(now_ts) if now_ts is not None else time.time()
        age = current - ts
        if age < 0 or age > max_age:
            logger.debug(
                "用户最近活跃端信号已过期：cid=%s age=%.0fs max=%.0fs", cid, age, max_age
            )
            return ""

        channel = classify_conversation_channel(cid)
        if not channel:
            logger.debug("会话命名空间无法判定端：cid=%s", cid)
        return channel
    except Exception as exc:  # noqa: BLE001 - 探测失败一律降级为「未知」
        logger.warning("用户最近活跃端探测失败: %s", exc)
        return ""


__all__ = ["DEFAULT_MAX_AGE_SECONDS", "detect_user_active_channel"]
