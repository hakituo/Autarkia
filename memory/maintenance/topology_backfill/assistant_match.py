"""assistant 事件到手机回复链的配对。

一条服务端 assistant 事件在手机上可能是多个气泡节点；``RoomChain.text``
已经是同一变体链的拼接正文。配对按「整条链正文」而不是单节点比较。
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Set, Tuple

from .common import closest, content
from .matching import normalize_text, quick_similarity, similarity
from .model import RoomChain, RoomNode, RoomSession, ServerTurn

FUZZY_WINDOW_SECONDS = 900.0
FUZZY_THRESHOLD = 0.85
ASSISTANT_ONLY_THRESHOLD = 0.9
FUZZY_MARGIN = 0.02
MIN_FUZZY_LEN = 8

Resolved = Dict[int, Tuple[str, Any, str, str]]


def match_assistant_exact(
    turns: Sequence[ServerTurn],
    chain_index: Dict[str, List[RoomChain]],
    used_chains: Set[str],
    resolved: Resolved,
) -> None:
    for index, turn in enumerate(turns):
        if not turn.assistant_events:
            continue
        norm = normalize_text(content(turn.assistant_events[0]))
        candidates = [
            chain
            for chain in chain_index.get(norm, [])
            if chain.root.node_id not in used_chains
        ]
        pick = closest(
            candidates,
            turn.occurred_at,
            lambda chain: chain.user.timestamp,
            max_delta=None if norm else FUZZY_WINDOW_SECONDS,
            tie_seconds=5.0,
        )
        if pick is not None:
            used_chains.add(pick.root.node_id)
            resolved[index] = ("chain", pick, "assistant_exact", "high")


def match_assistant_fuzzy(
    session: RoomSession,
    turns: Sequence[ServerTurn],
    used_chains: Set[str],
    resolved: Resolved,
) -> None:
    for index, turn in enumerate(turns):
        if index in resolved or not turn.assistant_events:
            continue
        norm = normalize_text(content(turn.assistant_events[0]))
        if len(norm) < MIN_FUZZY_LEN:
            continue
        scored = []
        for chain in session.chains:
            if chain.root.node_id in used_chains:
                continue
            if abs(chain.user.timestamp - turn.occurred_at) > FUZZY_WINDOW_SECONDS:
                continue
            other = normalize_text(chain.text)
            if quick_similarity(norm, other) < 0.7:
                continue
            scored.append((similarity(norm, other), chain))
        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored or scored[0][0] < FUZZY_THRESHOLD:
            continue
        if len(scored) > 1 and scored[0][0] - scored[1][0] < FUZZY_MARGIN:
            continue
        used_chains.add(scored[0][1].root.node_id)
        resolved[index] = ("chain", scored[0][1], "assistant_fuzzy", "medium")


def match_assistant_only(
    session: RoomSession,
    turns: Sequence[ServerTurn],
    assistant_index: Dict[str, List[RoomNode]],
    resolved: Resolved,
) -> None:
    """主动消息等没有 user 事件的轮，按单节点匹配。"""
    for index, turn in enumerate(turns):
        if index in resolved or turn.user_events or not turn.assistant_events:
            continue
        norm = normalize_text(content(turn.assistant_events[0]))
        pick = closest(
            assistant_index.get(norm, []),
            turn.occurred_at,
            lambda node: node.timestamp,
            tie_seconds=5.0,
        )
        if pick is not None:
            resolved[index] = ("node", pick, "assistant_only_exact", "high")
            continue
        if len(norm) < MIN_FUZZY_LEN:
            continue
        scored = []
        for node in session.assistant_nodes:
            if abs(node.timestamp - turn.occurred_at) > FUZZY_WINDOW_SECONDS:
                continue
            other = normalize_text(node.text)
            if quick_similarity(norm, other) < 0.7:
                continue
            scored.append((similarity(norm, other), node))
        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored or scored[0][0] < ASSISTANT_ONLY_THRESHOLD:
            continue
        if len(scored) > 1 and scored[0][0] - scored[1][0] < FUZZY_MARGIN:
            continue
        resolved[index] = ("node", scored[0][1], "assistant_only_fuzzy", "medium")


__all__ = [
    "ASSISTANT_ONLY_THRESHOLD",
    "FUZZY_MARGIN",
    "FUZZY_THRESHOLD",
    "FUZZY_WINDOW_SECONDS",
    "MIN_FUZZY_LEN",
    "Resolved",
    "match_assistant_exact",
    "match_assistant_fuzzy",
    "match_assistant_only",
]
