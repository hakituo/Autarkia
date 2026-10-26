"""加权记忆与原始事件的关联审计（v3 D8 / C2）。

输出四类计数，保证"complete / partial / unknown 数量守恒"：
- ``linked_event_ref``：``metadata.event_ref.event_id`` 能对上原始事件；
- ``linked_turn_only``：只有 turn 级 ``message_id`` + role 能唯一对上；
- ``ambiguous_turn``：同 role 同 message_id 有多条事件，无法唯一确定；
- ``legacy_only``：完全没有可回指的原始事件（不得伪称可从聊天重建）。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Tuple

LINKED_EVENT_REF = "linked_event_ref"
LINKED_TURN_ONLY = "linked_turn_only"
AMBIGUOUS_TURN = "ambiguous_turn"
LEGACY_ONLY = "legacy_only"
CATEGORIES = (LINKED_EVENT_REF, LINKED_TURN_ONLY, AMBIGUOUS_TURN, LEGACY_ONLY)


def _conversation_from_ref(ref: Mapping[str, Any]) -> str:
    cid = str(ref.get("conversation_id") or "").strip()
    if cid:
        return cid
    rel = str(ref.get("relative_path") or "").strip()
    name = rel.replace("\\", "/").rsplit("/", 1)[-1]
    return name[: -len(".jsonl")] if name.endswith(".jsonl") else ""


def associate_records_with_events(
    records: Iterable[Mapping[str, Any]],
    event_index: Mapping[str, Any],
    *,
    sample_limit: int = 20,
) -> Dict[str, Any]:
    """``event_index`` 由 ``build_event_index`` 生成。"""
    by_event = event_index["by_event_id"]
    by_turn = event_index["by_turn"]
    counts: Dict[str, int] = {key: 0 for key in CATEGORIES}
    samples: Dict[str, List[str]] = {key: [] for key in CATEGORIES}
    total = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        total += 1
        memory_id = str(record.get("id") or "")
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        ref = metadata.get("event_ref") if isinstance(metadata, dict) else None
        event_id = str((ref or {}).get("event_id") or "") if isinstance(ref, dict) else ""

        if event_id and event_id in by_event:
            kind = LINKED_EVENT_REF
        else:
            role = str(record.get("role") or record.get("source") or "").strip().lower()
            message_id = str(metadata.get("message_id") or "").strip()
            conversation = _conversation_from_ref(ref) if isinstance(ref, dict) else ""
            candidates = by_turn.get((role, conversation, message_id), ())
            if not candidates and conversation:
                candidates = by_turn.get((role, "", message_id), ())
            if len(candidates) == 1:
                kind = LINKED_TURN_ONLY
            elif len(candidates) > 1:
                kind = AMBIGUOUS_TURN
            else:
                kind = LEGACY_ONLY
        counts[kind] += 1
        if len(samples[kind]) < sample_limit:
            samples[kind].append(memory_id)
    return {
        "denominator": total,
        "counts": counts,
        "conservation_ok": sum(counts.values()) == total,
        "samples": samples,
        "dedupe_key": "记忆 id",
        "note": "legacy_only 是唯一现存来源，不得当作可重建内容清理",
    }


def build_event_index(events: Iterable[Any]) -> Dict[str, Any]:
    """按 event_id 与 (role, conversation, message_id) 建索引。

    ``by_event_detail`` 供迁移脚本补写 ``event_ref`` 时取来源元数据；
    旧调用方只读 ``by_event_id`` / ``by_turn``，新增字段不影响口径。
    """
    by_event: Dict[str, str] = {}
    by_event_detail: Dict[str, Dict[str, Any]] = {}
    by_turn: Dict[Tuple[str, str, str], List[str]] = defaultdict(list)
    total = 0
    for item in events:
        event = getattr(item, "normalized", None)
        if event is None:
            continue
        total += 1
        role = str(event.speaker_role or "").lower()
        message_id = str(event.turn_id or "").strip()
        if event.event_id:
            by_event[event.event_id] = event.event_id
            by_event_detail[event.event_id] = {
                "event_id": event.event_id,
                "conversation_id": event.conversation_id,
                "role": role,
                "message_id": message_id,
                "timestamp": event.occurred_at,
                "relative_path": str(getattr(item, "relative_path", "") or ""),
                "storage_scope": event.namespace,
            }
        if role and message_id:
            by_turn[(role, event.conversation_id, message_id)].append(event.event_id)
            by_turn[(role, "", message_id)].append(event.event_id)
    return {
        "by_event_id": by_event,
        "by_event_detail": by_event_detail,
        "by_turn": dict(by_turn),
        "events_total": total,
    }


def orphan_event_stats(events: Iterable[Any], records: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """原始事件里完全没有记忆引用的比例（信息项，不作为错误）。"""
    referenced = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        ref = metadata.get("event_ref") if isinstance(metadata, dict) else None
        event_id = str((ref or {}).get("event_id") or "") if isinstance(ref, dict) else ""
        if event_id:
            referenced.add(event_id)
    total = 0
    orphan = 0
    for item in events:
        event = getattr(item, "normalized", None)
        if event is None:
            continue
        total += 1
        if event.event_id and event.event_id not in referenced:
            orphan += 1
    return {
        "denominator": total,
        "orphan": orphan,
        "rate": round(orphan / total, 4) if total else None,
        "note": "未被任何记忆引用属正常（原始事件始终保留）",
    }
