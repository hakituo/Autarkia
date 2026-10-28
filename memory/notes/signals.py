"""梗概上的画像信号 → 人物档案门控（替代旧逐条蒸馏的 ``distillation_metadata``）。

提取器每段同次输出 ``people_mentions`` / ``role_update_candidates``，随梗概落盘。
信号是**整段**的：v7 把同一份信号复制到该段每条梗概上，这里按段合并成一条线索，
来源取该段全部梗概的来源事件并集（人物可能出现在任一话题里），已分析计数也按段算。
按 scope 读出「段结束时间晚于上次处理时间」且已分析的段，线索带 ``event_ids``，门控按来源命中。
"""

from __future__ import annotations

from typing import Any

from . import legacy
from .store import NoteStore


def _segments(store: NoteStore) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for cid in legacy.readable_conversations(store):  # v2 过渡期新旧双读
        for note in legacy.readable_notes(store, cid, include_covered=False):  # 同段不算两遍
            key = (str(note.get("conversation_id") or cid), str(note.get("source_segment_id") or ""))
            grouped.setdefault(key, []).append(note)
    return grouped


def _merged(values: list[list[str]]) -> list[str]:
    out: list[str] = []
    for items in values:
        for item in items:
            if item not in out:
                out.append(item)
    return out


def collect_note_signals(scope: str, last_processed_ts: float) -> dict[str, Any]:
    people: list[dict[str, Any]] = []
    role_updates: list[dict[str, Any]] = []
    analyzed = 0
    for (cid, segment_id), notes in _segments(NoteStore(scope)).items():
        flagged = [note for note in notes if note.get("profile_signal_analyzed")]
        if not flagged:
            continue
        ended = max(float(n.get("occurred_to") or n.get("recorded_from") or 0) for n in notes)
        if ended <= last_processed_ts:
            continue
        analyzed += 1
        base = {
            "timestamp": ended,
            "note_id": str(flagged[0].get("note_id") or ""),
            "segment_id": segment_id,
            "conversation_id": cid,
            "event_ids": _merged([[str(e) for e in n.get("source_event_ids") or []] for n in notes]),
        }
        mentions = _merged([list(n.get("people_mentions") or []) for n in flagged])
        updates = _merged([list(n.get("role_update_candidates") or []) for n in flagged])
        if mentions:
            people.append({**base, "hints": mentions})
        if updates:
            role_updates.append({**base, "hints": updates})
    return {"people": people, "role_updates": role_updates, "analyzed_count": analyzed}


__all__ = ["collect_note_signals"]
