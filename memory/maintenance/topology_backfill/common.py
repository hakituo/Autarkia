"""事件字段读取与通用匹配工具（纯函数，不读文件）。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence

from .model import EventDecision, RoomNode


def role(event: Dict[str, Any]) -> str:
    return str(event.get("role") or "").strip().lower()


def event_type(event: Dict[str, Any]) -> str:
    return str(event.get("event_type") or "").strip().lower()


def content(event: Dict[str, Any]) -> str:
    return str(event.get("content") or "")


def timestamp(event: Dict[str, Any]) -> float:
    return float(event.get("timestamp") or 0.0)


def event_id(event: Dict[str, Any]) -> str:
    value = str(event.get("event_id") or "").strip()
    if value:
        return value
    return (
        f"{event.get('message_id') or ''}:{event.get('role') or ''}:"
        f"{event.get('timestamp') or ''}"
    )


def index_items(items: Sequence[Any], key) -> Dict[str, List[Any]]:
    indexed: Dict[str, List[Any]] = defaultdict(list)
    for item in items:
        value = key(item)
        if value:
            indexed[value].append(item)
    return indexed


def closest(
    candidates: Sequence[Any],
    moment: float,
    key,
    *,
    max_delta: Optional[float] = None,
    tie_seconds: float = 1.0,
) -> Optional[Any]:
    scored = []
    for candidate in candidates:
        delta = abs(float(key(candidate)) - moment)
        if max_delta is not None and delta > max_delta:
            continue
        scored.append((delta, candidate))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0])
    if len(scored) > 1 and abs(scored[1][0] - scored[0][0]) <= tie_seconds:
        return None
    return scored[0][1]


def assign(
    decision: EventDecision, node: RoomNode, method: str, confidence: str
) -> None:
    decision.client_node_id = node.node_id
    decision.parent_node_id = node.parent_id
    decision.is_root = not node.parent_id
    decision.match_method = method
    decision.confidence = confidence
    decision.reason = ""


__all__ = [
    "assign",
    "closest",
    "content",
    "event_id",
    "event_type",
    "index_items",
    "role",
    "timestamp",
]
