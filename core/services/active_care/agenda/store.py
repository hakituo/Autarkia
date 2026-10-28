"""开场议程的持久化：轻问候发出后，「想跟他聊的那件事」存在这里，等主聊天一步步带过去。

文件结构（每个角色一份 ``agenda.json``）::

    {
      "active": {...} | null,        # 当前未结束的议程，同一时刻最多一条
      "recent_openers": [{"text", "ts"}, ...],   # 最近的开场白，供生成时去重
      "closed": [{..., "closed_reason", "closed_ts"}, ...]  # 最近结束的议程，排查用
    }

结束方式：
- 主聊天模型判断这件事聊到了 / 他去做了 / 他不想聊，调用 ``close_agenda`` 清掉；
- 安全上限：开场后 ``MAX_AGE_SECONDS`` 仍没清掉就视为作废，防止同一件事一直被注入。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from core.services.active_care.agenda import paths
from core.utils.async_locks import LazyAsyncLock
from core.utils.atomic_io import safe_json_dump, safe_json_load
from core.utils.logger import get_logger

logger = get_logger("ACTIVE_CARE_AGENDA")

#: 议程最长存活时间：正常靠模型自己清，这只是兜底
MAX_AGE_SECONDS = 24 * 3600
#: 保留多少条最近开场白用于去重
RECENT_OPENERS_LIMIT = 12
#: 保留多少条已结束议程（只供排查）
CLOSED_HISTORY_LIMIT = 20

_LOCK = LazyAsyncLock()


@dataclass
class Agenda:
    """一条开场议程。"""

    topic: str
    detail: str = ""
    source_id: str = ""
    intent: str = ""
    opener: str = ""
    agenda_id: str = field(default_factory=lambda: f"agenda_{uuid.uuid4().hex[:10]}")
    created_ts: float = field(default_factory=time.time)
    turns: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Optional["Agenda"]:
        if not isinstance(data, dict) or not str(data.get("topic") or "").strip():
            return None
        return cls(
            topic=str(data.get("topic") or "").strip(),
            detail=str(data.get("detail") or "").strip(),
            source_id=str(data.get("source_id") or "").strip(),
            intent=str(data.get("intent") or "").strip(),
            opener=str(data.get("opener") or "").strip(),
            agenda_id=str(data.get("agenda_id") or "") or f"agenda_{uuid.uuid4().hex[:10]}",
            created_ts=float(data.get("created_ts") or 0.0),
            turns=int(data.get("turns") or 0),
        )

    def expired(self, now: float) -> bool:
        return now - self.created_ts >= MAX_AGE_SECONDS


def _empty() -> Dict[str, Any]:
    return {"active": None, "recent_openers": [], "closed": []}


def _read(scope: str) -> Dict[str, Any]:
    data = safe_json_load(paths.agenda_file(scope), default=None)
    if not isinstance(data, dict):
        return _empty()
    data.setdefault("active", None)
    data.setdefault("recent_openers", [])
    data.setdefault("closed", [])
    return data


def _write(scope: str, data: Dict[str, Any]) -> None:
    safe_json_dump(data, paths.agenda_file(scope))


def _archive(data: Dict[str, Any], agenda: Agenda, reason: str, now: float) -> None:
    record = {**asdict(agenda), "closed_reason": reason, "closed_ts": now}
    data["closed"] = ([record] + list(data.get("closed") or []))[:CLOSED_HISTORY_LIMIT]
    data["active"] = None


async def get_active_agenda(scope: str, *, now: Optional[float] = None) -> Optional[Agenda]:
    """当前未结束的议程；过期的顺手归档并返回 None。"""
    now = time.time() if now is None else now
    async with _LOCK:
        data = await asyncio.to_thread(_read, scope)
        agenda = Agenda.from_dict(data.get("active") or {})
        if agenda is None:
            return None
        if agenda.expired(now):
            _archive(data, agenda, "expired", now)
            await asyncio.to_thread(_write, scope, data)
            logger.info("Active Care 议程过期作废 scope=%s topic=%s", scope, agenda.topic[:40])
            return None
        return agenda


async def open_agenda(scope: str, agenda: Agenda, *, now: Optional[float] = None) -> Agenda:
    """写入新议程并记下开场白；已有未结束的议程会被替换（旧的记为 replaced）。"""
    now = time.time() if now is None else now
    async with _LOCK:
        data = await asyncio.to_thread(_read, scope)
        previous = Agenda.from_dict(data.get("active") or {})
        if previous is not None:
            _archive(data, previous, "replaced", now)
        data["active"] = asdict(agenda)
        if agenda.opener:
            openers = [{"text": agenda.opener, "ts": now}] + list(data.get("recent_openers") or [])
            data["recent_openers"] = openers[:RECENT_OPENERS_LIMIT]
        await asyncio.to_thread(_write, scope, data)
    logger.info("Active Care 议程开启 scope=%s topic=%s", scope, agenda.topic[:40])
    return agenda


async def close_agenda(scope: str, reason: str, *, now: Optional[float] = None) -> Optional[Agenda]:
    """结束当前议程；没有议程时返回 None。"""
    now = time.time() if now is None else now
    async with _LOCK:
        data = await asyncio.to_thread(_read, scope)
        agenda = Agenda.from_dict(data.get("active") or {})
        if agenda is None:
            return None
        _archive(data, agenda, str(reason or "closed").strip()[:40] or "closed", now)
        await asyncio.to_thread(_write, scope, data)
    logger.info("Active Care 议程结束 scope=%s reason=%s topic=%s", scope, reason, agenda.topic[:40])
    return agenda


async def record_agenda_turn(scope: str, agenda_id: str) -> int:
    """主聊天注入一次议程后调用：轮数 +1，返回新轮数（议程已换掉时返回 -1）。"""
    async with _LOCK:
        data = await asyncio.to_thread(_read, scope)
        active = data.get("active")
        if not isinstance(active, dict) or active.get("agenda_id") != agenda_id:
            return -1
        active["turns"] = int(active.get("turns") or 0) + 1
        await asyncio.to_thread(_write, scope, data)
        return active["turns"]


async def recent_openers(scope: str) -> List[str]:
    """最近用过的开场白（新的在前）。"""
    async with _LOCK:
        data = await asyncio.to_thread(_read, scope)
    return [
        str(item.get("text") or "").strip()
        for item in data.get("recent_openers") or []
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]


__all__ = [
    "MAX_AGE_SECONDS",
    "Agenda",
    "close_agenda",
    "get_active_agenda",
    "open_agenda",
    "record_agenda_turn",
    "recent_openers",
]
