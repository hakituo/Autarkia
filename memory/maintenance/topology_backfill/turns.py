"""把服务端事件按 ``message_id`` 聚成 turn（user / assistant / thought）。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Sequence

from .common import event_id, event_type, role, timestamp
from .model import EventDecision, ServerTurn

_ASSISTANT_TYPES = frozenset({"chat_reply", "proactive_message"})


def build_server_turns(events: Sequence[Dict[str, Any]]) -> List[ServerTurn]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for event in events:
        message_id = str(event.get("message_id") or "").strip()
        grouped[message_id or f"event:{event_id(event)}"].append(event)

    turns: List[ServerTurn] = []
    for message_id, items in grouped.items():
        user_events = [event for event in items if role(event) == "user"]
        assistant_events = [
            event
            for event in items
            if role(event) == "assistant" or event_type(event) in _ASSISTANT_TYPES
        ]
        system_events = [
            event
            for event in items
            if role(event) == "system" and event_type(event) not in _ASSISTANT_TYPES
        ]
        occurred_at = max(
            (timestamp(event) for event in assistant_events),
            default=max((timestamp(event) for event in items), default=0.0),
        )
        turns.append(
            ServerTurn(
                message_id=message_id,
                events=list(items),
                user_events=user_events,
                assistant_events=assistant_events,
                system_events=system_events,
                occurred_at=occurred_at,
            )
        )
    turns.sort(key=lambda turn: (turn.occurred_at, turn.message_id))
    return turns


def base_decision(event: Dict[str, Any]) -> EventDecision:
    return EventDecision(
        event_id=event_id(event),
        conversation_id=str(event.get("conversation_id") or ""),
        role=role(event),
        event_type=event_type(event),
        message_id=str(event.get("message_id") or ""),
        occurred_at=timestamp(event),
    )


__all__ = ["base_decision", "build_server_turns"]
