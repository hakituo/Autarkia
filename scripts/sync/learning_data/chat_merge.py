"""聊天记录的并集合并：JSONL 按 ``event_id``、当天 index.json 按 ``relative_path``。

聊天历史与学习数据不同：一个会话一天一个 JSONL，两个系统都可能往同一个文件追加，
整文件「谁新用谁」会把另一边的消息直接丢掉。这里改成并集合并：

- :func:`union_jsonl`：按 ``event_id`` 去重取并集，再按 ``(timestamp, 行内容)`` 排序。
  排序键完全由内容决定，因此「先 A 后 B」与「先 B 后 A」结果相同；对已经合并过
  的结果再合并一次也不变（幂等）；
- :func:`union_day_index`：把两边的 ``files`` 数组合并（按 ``relative_path`` 去重，
  优先保留带 ``readable_title`` 的条目）并按路径排序。

:func:`union_bytes` 是执行层用的统一入口，按合并策略分派；记忆（``memory_union``）
转交 :func:`scripts.sync.learning_data.memory_merge.union_memory_json`。

派生数据不在这里处理：``indexes/*.db`` 等 SQLite 索引不进同步清单，由各系统本地
重建（见 ``core/services/chat_history_index.py`` 的 ``ensure_sync``）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Dict, Optional, Tuple

from scripts.sync.learning_data.dated_state_merge import union_dated_state
from scripts.sync.learning_data.items import (
    MERGE_DATED_STATE,
    MERGE_INDEX,
    MERGE_JSONL,
    MERGE_LIFE_STATE,
    MERGE_MEMORY,
    MERGE_TEXT_RICHER,
)
from scripts.sync.learning_data.life_state_merge import union_life_state
from scripts.sync.learning_data.memory_merge import union_memory_json
from scripts.sync.learning_data.text_merge import union_text_richer

#: 记录里可能承载时间的字段，按常见程度排列（聊天用 timestamp，
#: 设备流水用 server_timestamp / last_updated，操作流水用 time）
_TIMESTAMP_FIELDS = (
    "timestamp",
    "server_timestamp",
    "time",
    "last_updated",
    "created_at",
    "last_access_time",
)


def union_bytes(mode: str, left: bytes, right: bytes) -> Optional[bytes]:
    """按合并策略把两侧内容并集；未知策略返回 None（由调用方按冲突处理）。"""
    if mode == MERGE_JSONL:
        return union_jsonl(left, right)
    if mode == MERGE_INDEX:
        return union_day_index(left, right)
    if mode == MERGE_MEMORY:
        return union_memory_json(left, right)
    if mode == MERGE_TEXT_RICHER:
        return union_text_richer(left, right)
    if mode == MERGE_DATED_STATE:
        return union_dated_state(left, right)
    if mode == MERGE_LIFE_STATE:
        return union_life_state(left, right)
    return None


def union_jsonl(left: bytes, right: bytes) -> bytes:
    """JSONL 行级并集：``event_id`` 相同视为同一条，其余按 ``(timestamp, 行)`` 排序。"""
    winners: Dict[str, Tuple[float, str]] = {}
    for raw in (left, right):
        for line in _iter_lines(raw):
            record = _load(line)
            event_id = str((record or {}).get("event_id") or "").strip()
            key = f"id:{event_id}" if event_id else f"sig:{_sha1(line)}"
            order = (_timestamp(record), line)
            current = winners.get(key)
            if current is None or order < current:
                winners[key] = order
    if not winners:
        return b""
    ordered = sorted(winners.values())
    return ("\n".join(line for _, line in ordered) + "\n").encode("utf-8")


def union_day_index(left: bytes, right: bytes) -> bytes:
    """当天 ``index.json`` 的条目级并集：按 ``relative_path`` 去重后排序。"""
    entries: Dict[str, dict] = {}
    for raw in (left, right):
        payload = _load_json(raw)
        for item in (payload or {}).get("files") or []:
            if not isinstance(item, dict):
                continue
            rel = str(item.get("relative_path") or "").strip()
            if not rel:
                continue
            current = entries.get(rel)
            if current is None or _index_rank(item) > _index_rank(current):
                entries[rel] = item
    ordered = [entries[rel] for rel in sorted(entries)]
    return _dump_json({"files": ordered})


def _iter_lines(raw: bytes) -> list[str]:
    if not raw:
        return []
    text = raw.decode("utf-8", errors="replace")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _load(line: str) -> Optional[dict]:
    try:
        payload = json.loads(line)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _load_json(raw: bytes) -> Optional[dict]:
    if not raw:
        return None
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _timestamp(record: Optional[dict]) -> float:
    """取记录时间并统一成秒级浮点；取不到返回 0.0。

    兼容三种写法：秒级数字、毫秒级数字、ISO 8601 字符串
    （``2026-09-26T21:51:29.631983Z`` / ``2026-09-27T05:51:30+08:00``）。
    字段名也按常见程度兜底，否则设备流水这类只有 ``server_timestamp``
    的记录会全部落到 0，合并后顺序全乱。
    """
    for field in _TIMESTAMP_FIELDS:
        raw = (record or {}).get(field)
        if raw is None or isinstance(raw, bool):
            continue
        text = str(raw).strip()
        if not text:
            continue
        try:
            value = float(text)
        except ValueError:
            parsed = _iso_timestamp(text)
            if parsed is not None:
                return parsed
            continue
        return value / 1000.0 if value > 1e12 else value
    return 0.0


def _iso_timestamp(text: str) -> Optional[float]:
    """解析 ISO 8601 时间串；带 Z 或时区偏移都能算成同一时间轴。"""
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        return datetime.fromisoformat(candidate).timestamp()
    except ValueError:
        return None


def _index_rank(item: dict) -> int:
    """条目优先级：带可读标题的条目更完整，合并时优先保留。"""
    return 1 if str(item.get("readable_title") or "").strip() else 0


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _dump_json(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
