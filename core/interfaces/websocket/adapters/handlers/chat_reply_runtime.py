"""聊天被动回复与睡眠恢复运行时状态。"""

from __future__ import annotations
from core.utils.logger import get_logger

import asyncio

import time
from typing import Any, Dict, List, Optional, Tuple

from core.services.character_daily.activity_model import (
    ACTIVITY_VERBS_ONGOING,
    ActivityType,
    DO_NOT_DISTURB_ACTIVITIES,
)
from core.services.character_daily.reply_hints import (
    build_busy_done_hint,
    build_morning_after_hint,
)

logger = get_logger(__name__)

_DND_PENDING: Dict[str, Dict[str, Any]] = {}
_LAST_REPLY_STATE: Dict[str, Dict[str, Any]] = {}
_SLEEP_RECOVERY_TRACKING: Dict[str, Dict[str, Any]] = {}
# 软延迟合并批：同一会话处于软延迟等待期时，新到的消息并入同一批，
# 由首条消息的处理协程在截止后统一回复一次，避免每条消息各自延迟、各自回复。
_SOFT_DELAY_BATCHES: Dict[str, Dict[str, Any]] = {}


def get_or_create_soft_delay_batch(
    cid: str,
    content: str,
    activity: str,
    deadline_ts: float,
) -> Tuple[Dict[str, Any], bool]:
    """原子获取或创建软延迟合并批。

    Returns:
        (批对象, 是否为本协程新建)。False 表示批已存在，调用方应转而 join。
    """
    batch = _SOFT_DELAY_BATCHES.get(cid)
    if batch is not None:
        return batch, False
    batch = {
        "messages": [str(content or "")],
        "activity": str(activity or ""),
        "first_ts": time.time(),
        "deadline_ts": float(deadline_ts),
        "joined": asyncio.Event(),
    }
    _SOFT_DELAY_BATCHES[cid] = batch
    return batch, True


def join_soft_delay_batch(
    cid: str,
    content: str,
    grace_seconds: float,
    max_wait_seconds: float,
) -> Optional[float]:
    """把新消息并入进行中的软延迟批，返回顺延后的截止时间；批不存在返回 None。

    每并入一条顺延 ``grace_seconds``，但总等待不超过首条消息起 ``max_wait_seconds``。
    """
    batch = _SOFT_DELAY_BATCHES.get(cid)
    if batch is None:
        return None
    batch["messages"].append(str(content or ""))
    now = time.time()
    batch["deadline_ts"] = max(
        min(
            float(batch["deadline_ts"]) + max(0.0, float(grace_seconds)),
            float(batch["first_ts"]) + max(1.0, float(max_wait_seconds)),
        ),
        now,
    )
    batch["joined"].set()
    return float(batch["deadline_ts"])


def pop_soft_delay_batch(cid: str) -> Optional[Dict[str, Any]]:
    """移除并返回软延迟批（仅 owner 协程在等待结束/取消后调用）。"""
    return _SOFT_DELAY_BATCHES.pop(cid, None)


async def wait_soft_delay_batch(cid: str) -> List[str]:
    """等待软延迟批截止（期间有新消息并入会顺延），返回批内全部消息并移除批。

    正常结束时批会被移除；CancelledError 传播时批保留在原处，
    由调用方的取消分支负责取出并转存。
    """
    batch = _SOFT_DELAY_BATCHES.get(cid)
    if batch is None:
        return []
    while True:
        remaining = float(batch["deadline_ts"]) - time.time()
        if remaining <= 0:
            break
        try:
            await asyncio.wait_for(batch["joined"].wait(), timeout=remaining)
        except asyncio.TimeoutError:
            break
        batch["joined"].clear()
    _SOFT_DELAY_BATCHES.pop(cid, None)
    return list(batch["messages"])


def _build_sleep_resume_message(after_summary: Dict[str, Any]) -> str:
    """根据睡眠恢复结果构造主动消息。"""
    phase = str(after_summary.get("phase") or "")
    nightmare_level = str(after_summary.get("nightmare_level") or "none")
    if phase == "sleeping":
        if nightmare_level != "none":
            return "我还是有点困，先再睡一会儿啦，有事你再叫我。"
        return "我先继续睡会儿啦，有事再叫我。"
    if phase == "sleep_later":
        return "我先缓一会儿，等会儿再去睡，不是故意突然消失。"
    return ""


async def _notify_sleep_resume_message(
    cid: str,
    role_id: str,
    before_summary: Dict[str, Any],
    after_summary: Dict[str, Any],
) -> None:
    """静默后决定继续睡/稍后再睡时，主动补一条消息。"""
    # 兼容传入 SleepRuntimeState（无 .get 方法）或 dict 两种形态
    if hasattr(before_summary, "to_dict"):
        before_summary = before_summary.to_dict()
    if hasattr(after_summary, "to_dict"):
        after_summary = after_summary.to_dict()
    before_phase = str(before_summary.get("phase") or "")
    after_phase = str(after_summary.get("phase") or "")
    if before_phase not in {"night_awake", "stay_up_late", "sleep_later"}:
        return
    if after_phase not in {"sleeping", "sleep_later"}:
        return

    content = _build_sleep_resume_message(after_summary)
    if not content:
        return

    try:
        from core.core_engine.service_singletons import get_aveline_service
        from core.services.active_care.core.persona_resolver import PersonaResolver
        from core.services.active_care.core.service import get_active_care_service

        aveline_service = get_aveline_service()
        if aveline_service is None:
            return

        active_care_service = get_active_care_service()
        storage = active_care_service.storage if active_care_service else None
        profile_filename = PersonaResolver.resolve_profile_filename_static(
            cid,
            storage,
        ) if storage is not None else ""

        result = await aveline_service.dispatch_proactive_message(
            target_conversation_id=cid,
            content=content,
            thought=f"{role_id} 在夜间聊天后决定 {after_phase}",
        )
        if result.get("delivered") and active_care_service is not None:
            await active_care_service.on_assistant_message_sent(
                timestamp=time.time(),
                profile_filename=profile_filename,
            )
    except Exception as exc:
        logger.warning("发送重新入睡主动消息失败: %s", exc)


def record_successful_reply(cid: str, activity: str) -> None:
    """记录一次成功回复。"""
    _LAST_REPLY_STATE[cid] = {
        "last_reply_ts": time.time(),
        "activity": activity,
    }


def get_last_reply_state(cid: str) -> Tuple[float, str]:
    """获取最近一次成功回复状态。"""
    data = _LAST_REPLY_STATE.get(cid)
    if not data:
        return 0.0, ""
    return float(data.get("last_reply_ts", 0.0)), str(data.get("activity", ""))


def clear_last_reply_state(cid: str) -> None:
    """清空最近一次成功回复状态。"""
    _LAST_REPLY_STATE.pop(cid, None)


def cleanup_expired_dnd_pending(cooldown_seconds: float) -> None:
    """清理超过冷却时间的拒回累积。"""
    now = time.time()
    expired = [
        cid
        for cid, data in _DND_PENDING.items()
        if (now - float(data.get("last_ts", 0.0))) > cooldown_seconds
    ]
    for cid in expired:
        _DND_PENDING.pop(cid, None)


def get_pending_messages(cid: str) -> List[str]:
    """获取累积消息。"""
    data = _DND_PENDING.get(cid)
    if not data:
        return []
    return list(data.get("messages", []))


def get_pending_activity(cid: str) -> str:
    """获取累积时的活动类型。"""
    data = _DND_PENDING.get(cid)
    if not data:
        return ""
    return str(data.get("activity", ""))


def append_pending_message(
    cid: str,
    content: str,
    activity: str = "",
    role_id: str = "",
) -> None:
    """追加一条被延后处理的消息。

    Args:
        cid: 会话 ID
        content: 用户消息原文
        activity: 当时被拒回时角色的活动类型字符串
        role_id: 当时被拒回时角色对应的 role_id（做事结束后按 role 反查累积消息）
    """
    data = _DND_PENDING.get(cid)
    if data is None:
        data = {
            "messages": [],
            "last_ts": 0.0,
            "activity": activity,
            "role_id": str(role_id or "").strip().lower(),
        }
        _DND_PENDING[cid] = data
    data["messages"].append(content)
    data["last_ts"] = time.time()
    # 兼容旧数据：旧 _DND_PENDING 项没有 role_id 字段，这里补上
    if not data.get("role_id") and role_id:
        data["role_id"] = str(role_id or "").strip().lower()
    if len(data["messages"]) > 20:
        data["messages"] = data["messages"][-20:]


def get_pending_by_role_id(role_id: str) -> List[Dict[str, Any]]:
    """按 role_id 反查所有累积消息会话。

    用于：角色从忙碌切回可聊天时，把做事期间累积的消息
    走普通对话机制主动补回给用户。

    Args:
        role_id: 角色 ID（已 lower）

    Returns:
        [{"cid": str, "messages": List[str], "activity": str}, ...]
        列表已按 last_ts 升序，方便按时间顺序逐个处理
    """
    role = str(role_id or "").strip().lower()
    if not role:
        return []
    matched: List[Dict[str, Any]] = []
    for cid, data in _DND_PENDING.items():
        if str(data.get("role_id") or "").strip().lower() != role:
            continue
        messages = list(data.get("messages", []))
        if not messages:
            continue
        matched.append({
            "cid": cid,
            "messages": messages,
            "activity": str(data.get("activity", "")),
            "last_ts": float(data.get("last_ts", 0.0)),
        })
    matched.sort(key=lambda item: item.get("last_ts", 0.0))
    return matched


def clear_pending_messages(cid: str) -> None:
    """清空累积消息。"""
    _DND_PENDING.pop(cid, None)


def remove_pending_message(cid: str, content: str) -> None:
    """移除累积消息中与已回复内容相同的条目。

    当某条被延后(静默)累积的消息实际上已经通过正常聊天流或主动关怀
    被动回复过一次时，需要把它从待活动结束后统一处理的队列里剔除，
    避免活动结束(如打断 reading)时被二次注入主程序造成重复回复。
    """
    if not content:
        return
    data = _DND_PENDING.get(cid)
    if not data:
        return
    messages = data.get("messages", [])
    if content in messages:
        messages = [m for m in messages if m != content]
        data["messages"] = messages
        if not messages:
            _DND_PENDING.pop(cid, None)


def build_after_activity_done_hint(activity_str: str, pending: List[str]) -> str:
    """构建活动结束后的提示文本。"""
    if not pending:
        return ""
    activity = ActivityType.from_str(activity_str) if activity_str else ActivityType.IDLE
    if activity in DO_NOT_DISTURB_ACTIVITIES:
        return build_morning_after_hint(pending)
    activity_verb = ACTIVITY_VERBS_ONGOING.get(activity, "做事")
    return build_busy_done_hint(pending, activity_verb)


def has_sleep_recovery_tracking(cid: str) -> bool:
    """当前会话是否处于睡眠恢复等待期。"""
    return cid in _SLEEP_RECOVERY_TRACKING


async def cleanup_sleep_recovery_tasks_for_ws(ws_key: int) -> None:
    """清理某个 websocket 关联的睡眠恢复任务。"""
    to_cancel = [
        cid
        for cid, data in _SLEEP_RECOVERY_TRACKING.items()
        if int(data.get("ws_key", -1)) == int(ws_key)
    ]
    for cid in to_cancel:
        await cancel_sleep_recovery(cid)


async def cancel_sleep_recovery(cid: str) -> None:
    """取消某个会话的睡眠恢复任务。"""
    data = _SLEEP_RECOVERY_TRACKING.pop(cid, None)
    task = data.get("task") if data else None
    if isinstance(task, asyncio.Task) and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def schedule_sleep_recovery(
    *,
    cid: str,
    ws_key: int,
    role_id: str,
    silence_window_seconds: int,
) -> None:
    """为当前会话安排静默恢复判定。"""
    existing = _SLEEP_RECOVERY_TRACKING.get(cid)
    if existing:
        task = existing.get("task")
        if isinstance(task, asyncio.Task) and not task.done():
            task.cancel()

    async def _runner() -> None:
        try:
            await asyncio.sleep(max(1, int(silence_window_seconds or 180)))
            from core.services.life_simulation import get_life_simulation_service

            life_sim = get_life_simulation_service()
            if life_sim:
                before_summary = life_sim.get_sleep_summary(role_id)
                after_summary = await life_sim.finalize_sleep_recovery_check(role_id)
                await _notify_sleep_resume_message(
                    cid=cid,
                    role_id=role_id,
                    before_summary=before_summary,
                    after_summary=after_summary,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("睡眠静默恢复判定失败: %s", exc)
        finally:
            current = _SLEEP_RECOVERY_TRACKING.get(cid)
            if current and current.get("task") is task:
                _SLEEP_RECOVERY_TRACKING.pop(cid, None)

    task = asyncio.create_task(_runner())
    _SLEEP_RECOVERY_TRACKING[cid] = {
        "task": task,
        "ws_key": ws_key,
        "role_id": role_id,
        "silence_window_seconds": int(silence_window_seconds or 180),
    }
