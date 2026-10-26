"""审计指标：每项都带分母与去重键，便于复算（v3 C1）。"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Optional

from memory.audit.chat_events import ScannedEvent
from memory.topology.gating import content_hash, is_content_eligible

_PAIR_WINDOW_SECONDS = 120.0
_SHORT_TEXT_CHARS = 20


def event_distribution(events: Iterable[ScannedEvent]) -> Dict[str, Any]:
    roles: Counter = Counter()
    types: Counter = Counter()
    platforms: Counter = Counter()
    total = 0
    for item in events:
        total += 1
        event = item.normalized
        roles[event.speaker_role or "unknown"] += 1
        types[event.event_type or "unknown"] += 1
        platforms[event.platform or "(空)"] += 1
    return {
        "denominator": total,
        "dedupe_key": "event_id",
        "by_role": dict(sorted(roles.items())),
        "by_event_type": dict(sorted(types.items())),
        "by_platform": dict(sorted(platforms.items())),
    }


def _is_proactive(raw: Mapping[str, Any]) -> bool:
    metadata = raw.get("metadata")
    return bool(isinstance(metadata, dict) and metadata.get("is_proactive"))


def complete_exchange_stats(events: List[ScannedEvent]) -> Dict[str, Any]:
    """已完成普通 exchange 的成对率。

    分母只含 ``role=user`` + ``event_type=chat_message`` + ``content_eligible``
    的事件；主动消息、系统/调度、媒体占位不计入分母（它们是明确的其他类型）。
    配对键优先 ``(conversation_id, turn_id)``，无 turn_id 时退到同会话 120 秒内。
    """
    eligible = [
        item
        for item in events
        if item.normalized.speaker_role == "user"
        and item.normalized.event_type == "chat_message"
        and item.normalized.content_eligible
        and not _is_proactive(item.raw)
    ]
    proactive_skipped = sum(
        1 for item in events if item.normalized.speaker_role == "user" and _is_proactive(item.raw)
    )
    replies = [
        item
        for item in events
        if item.normalized.speaker_role == "assistant"
        and item.normalized.event_type in {"chat_reply", "chat_message"}
    ]
    by_turn = {
        (item.normalized.conversation_id, item.normalized.turn_id)
        for item in replies
        if item.normalized.turn_id
    }
    by_time = [
        (item.normalized.conversation_id, item.normalized.occurred_at) for item in replies
    ]
    matched = 0
    for item in eligible:
        event = item.normalized
        if event.turn_id and (event.conversation_id, event.turn_id) in by_turn:
            matched += 1
            continue
        if any(
            conversation == event.conversation_id
            and 0 <= timestamp - event.occurred_at <= _PAIR_WINDOW_SECONDS
            for conversation, timestamp in by_time
        ):
            matched += 1
    denominator = len(eligible)
    return {
        "denominator": denominator,
        "matched": matched,
        "rate": round(matched / denominator, 4) if denominator else None,
        "proactive_excluded": proactive_skipped,
        "dedupe_key": "(conversation_id, turn_id) 或同会话 120s",
        "note": "主动/系统/媒体事件不计入分母",
    }


def duplicate_stats(events: List[ScannedEvent]) -> Dict[str, Any]:
    """重复写入：幂等键重复 + 内容签名重复。"""
    keys: Counter = Counter()
    signatures: Counter = Counter()
    for item in events:
        event = item.normalized
        if event.idempotency_key:
            keys[event.idempotency_key] += 1
        if event.content_eligible:
            signatures[
                (
                    event.conversation_id,
                    event.speaker_role,
                    content_hash(event.content),
                    int(event.occurred_at),
                )
            ] += 1
    return {
        "idempotency_duplicates": sum(count - 1 for count in keys.values() if count > 1),
        "idempotency_keys": len(keys),
        "content_signature_duplicates": sum(
            count - 1 for count in signatures.values() if count > 1
        ),
        "content_signatures": len(signatures),
        "dedupe_key": "idempotency_key / (conversation, role, content_hash, 秒)",
    }


def short_text_stats(events: Iterable[ScannedEvent]) -> Dict[str, Any]:
    eligible = [item for item in events if item.normalized.content_eligible]
    short = sum(
        1
        for item in eligible
        if len(str(item.normalized.content or "").strip()) < _SHORT_TEXT_CHARS
    )
    return {
        "denominator": len(eligible),
        "short": short,
        "rate": round(short / len(eligible), 4) if eligible else None,
        "rule": f"content_eligible 且正文长度 < {_SHORT_TEXT_CHARS}",
    }


def system_marker_stats(events: Iterable[ScannedEvent]) -> Dict[str, Any]:
    """系统/调度内容进入提炼正文的数量（门槛为 0）。"""
    from core.utils.debug_markers import is_debug_context_message

    violations: Counter = Counter()
    total = 0
    for item in events:
        total += 1
        event = item.normalized
        if event.event_type in {"chat_thought", "system_prompt", "scheduled_task"}:
            if is_content_eligible(event.content, event_type=""):
                violations[event.event_type] += 1
        if is_debug_context_message(event.content):
            violations["debug_marker"] += 1
    return {
        "denominator": total,
        "violations": sum(violations.values()),
        "by_kind": dict(sorted(violations.items())),
        "rule": "event_type 属系统类但正文非空 / 正文含 debug 标记",
    }


def _percentile(values: List[float], ratio: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 3)


def weight_stats(records: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    weights = [
        float(record.get("weight") or 0.0)
        for record in records
        if isinstance(record, dict)
    ]
    return {
        "count": len(weights),
        "p50": _percentile(weights, 0.5),
        "p90": _percentile(weights, 0.9),
        "min": round(min(weights), 3) if weights else None,
        "max": round(max(weights), 3) if weights else None,
        "note": "分布本身不是验收目标，仅供与检索质量对照",
    }


def nightly_stats(
    records: Iterable[Mapping[str, Any]],
    *,
    now: float,
    threshold_hours: float = 1.0,
    window_hours: float = 24.0,
) -> Dict[str, Any]:
    total = 0
    distilled = 0
    eligible = 0
    outside_window = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        total += 1
        if bool(record.get("is_distilled")):
            distilled += 1
            continue
        timestamp = float(record.get("timestamp") or 0.0)
        if timestamp and now - timestamp >= threshold_hours * 3600:
            eligible += 1
        if timestamp and now - timestamp > window_hours * 3600:
            outside_window += 1
    return {
        "total": total,
        "distilled": distilled,
        "distilled_rate": round(distilled / total, 4) if total else None,
        "backlog": eligible,
        "outside_24h_window": outside_window,
        "dedupe_key": "记忆 id",
        "note": "outside_24h_window 在旧的 24h 资格窗口下永远不会被重试",
    }
