"""user 事件到手机用户节点的配对，以及重复提交 / 断父标记。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Sequence

from .common import assign, closest, content, timestamp
from .matching import (
    has_media_prefix,
    latest_wrapper_message,
    normalize_text,
    strip_media_prefix,
)
from .model import EventDecision, RoomNode, RoomSession

MEDIA_TYPES = frozenset({"image", "video", "voice", "attachment"})
USER_MATCH_WINDOW_SECONDS = 86400.0


def user_method(event: Dict[str, Any], node: RoomNode) -> tuple[str, str]:
    text = content(event)
    if has_media_prefix(text):
        caption = strip_media_prefix(text)
        if normalize_text(caption) == normalize_text(node.text):
            return "user_media", "high"
    if normalize_text(text) == normalize_text(node.text):
        return "user_exact", "high"
    latest = latest_wrapper_message(text)
    if latest and normalize_text(latest) == normalize_text(node.text):
        return "user_wrapper", "high"
    return "user_turn_anchor", "medium"


def match_user_event(
    decision: EventDecision,
    event: Dict[str, Any],
    user_index: Dict[str, List[RoomNode]],
    session: RoomSession,
) -> None:
    text = content(event)
    moment = timestamp(event)
    pick = closest(
        user_index.get(normalize_text(text), []),
        moment,
        lambda node: node.timestamp,
        max_delta=USER_MATCH_WINDOW_SECONDS,
        tie_seconds=2.0,
    )
    if pick is not None:
        assign(decision, pick, "user_exact", "high")
        return

    if has_media_prefix(text):
        caption = normalize_text(strip_media_prefix(text))
        if caption:
            pick = closest(
                user_index.get(caption, []),
                moment,
                lambda node: node.timestamp,
                max_delta=USER_MATCH_WINDOW_SECONDS,
                tie_seconds=2.0,
            )
            if pick is not None:
                assign(decision, pick, "user_media", "high")
                return
        media_nodes = [
            node for node in session.user_nodes if node.message_type in MEDIA_TYPES
        ]
        pick = closest(
            media_nodes,
            moment,
            lambda node: node.timestamp,
            max_delta=1800.0,
            tie_seconds=30.0,
        )
        if pick is not None:
            assign(decision, pick, "user_media_time", "medium")
            return

    latest = latest_wrapper_message(text)
    if latest:
        pick = closest(
            user_index.get(normalize_text(latest), []),
            moment,
            lambda node: node.timestamp,
            max_delta=USER_MATCH_WINDOW_SECONDS,
            tie_seconds=2.0,
        )
        if pick is not None:
            assign(decision, pick, "user_wrapper", "high")
            return

    decision.reason = "user_unmatched"


def mark_duplicates(decisions: Sequence[EventDecision]) -> None:
    """同一用户节点被多次提交时，只保留最早一条可提炼。"""
    grouped: Dict[str, List[EventDecision]] = defaultdict(list)
    for decision in decisions:
        if decision.role == "user" and decision.matched:
            grouped[decision.client_node_id].append(decision)
    for items in grouped.values():
        if len(items) <= 1:
            continue
        items.sort(key=lambda item: (item.occurred_at, item.event_id))
        for decision in items[1:]:
            decision.duplicate_submission = True


def mark_parent_without_event(decisions: Sequence[EventDecision]) -> None:
    matched_nodes = {decision.client_node_id for decision in decisions if decision.matched}
    for decision in decisions:
        if (
            decision.matched
            and decision.parent_node_id
            and decision.parent_node_id not in matched_nodes
        ):
            decision.parent_without_event = True


__all__ = [
    "MEDIA_TYPES",
    "USER_MATCH_WINDOW_SECONDS",
    "mark_duplicates",
    "mark_parent_without_event",
    "match_user_event",
    "user_method",
]
