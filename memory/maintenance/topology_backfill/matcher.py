"""把 Room 消息树与服务端事件按轮配对（预览用，只读）。

配对顺序：
1. assistant 正文精确匹配到一条回复链；
2. 模糊匹配（同会话、时间窗内、相似度阈值）；
3. 主动消息等 assistant-only 轮按单节点匹配；
4. user 事件优先挂到同一轮已配上的回复链所对应的用户节点；
5. thought 事件挂到同轮回复节点；
6. 同一用户节点被多次提交时标记 ``duplicate_submission``；
7. 父节点没有对应服务端事件时标记 ``parent_without_event``，不伪造新根。
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Set, Tuple

from .assistant_match import (
    match_assistant_exact,
    match_assistant_fuzzy,
    match_assistant_only,
)
from .common import assign, event_id, index_items
from .matching import normalize_text
from .model import EventDecision, RoomSession
from .turns import base_decision, build_server_turns
from .user_match import (
    mark_duplicates,
    mark_parent_without_event,
    match_user_event,
    user_method,
)


def match_session(
    session: RoomSession,
    events: Sequence[Dict[str, Any]],
) -> List[EventDecision]:
    turns = build_server_turns(events)
    decisions: Dict[str, EventDecision] = {}
    for event in events:
        decisions[event_id(event)] = base_decision(event)

    chain_index = index_items(session.chains, lambda chain: normalize_text(chain.text))
    empty_chains = [chain for chain in session.chains if not normalize_text(chain.text)]
    if empty_chains:
        chain_index[""] = empty_chains
    user_index = index_items(session.user_nodes, lambda node: normalize_text(node.text))
    assistant_index = index_items(
        session.assistant_nodes, lambda node: normalize_text(node.text)
    )

    used_chains: Set[str] = set()
    resolved: Dict[int, Tuple[str, Any, str, str]] = {}
    match_assistant_exact(turns, chain_index, used_chains, resolved)
    match_assistant_fuzzy(session, turns, used_chains, resolved)
    match_assistant_only(session, turns, assistant_index, resolved)

    for index, turn in enumerate(turns):
        if index not in resolved:
            continue
        kind, obj, method, confidence = resolved[index]
        node = obj.root if kind == "chain" else obj
        for event in turn.assistant_events:
            assign(decisions[event_id(event)], node, method, confidence)

    for index, turn in enumerate(turns):
        for event in turn.user_events:
            decision = decisions[event_id(event)]
            if index not in resolved:
                match_user_event(decision, event, user_index, session)
                continue
            kind, obj, _, _ = resolved[index]
            if kind == "chain":
                method, confidence = user_method(event, obj.user)
                assign(decision, obj.user, method, confidence)

    for index, turn in enumerate(turns):
        for event in turn.system_events:
            decision = decisions[event_id(event)]
            if index not in resolved:
                decision.reason = "assistant_unmatched"
                continue
            kind, obj, _, _ = resolved[index]
            node = obj.root if kind == "chain" else obj
            assign(decision, node, "thought_attached", "high")

    for decision in decisions.values():
        if decision.matched or decision.reason:
            continue
        if decision.role == "user":
            decision.reason = "user_unmatched"
        elif decision.role == "assistant":
            decision.reason = "assistant_unmatched"
        else:
            decision.reason = "system_unmatched"

    ordered = list(decisions.values())
    mark_duplicates(ordered)
    mark_parent_without_event(ordered)
    ordered.sort(key=lambda item: (item.occurred_at, item.event_id))
    return ordered


__all__ = ["match_session"]
