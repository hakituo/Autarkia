"""只读 topology / segment 回放（v3 C4）。

不预设"现有字段足够"：先按信封字段建树，再把每条 root→leaf 路径过一遍分段器，
输出段数、轮数/字数分布、idle 分布、纯寒暄占比、不可重建样本与迟到事件影响。
参数（30/40/8000 等）只作比较，不写死成产品默认值。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from memory.topology.segments import build_segments, group_turns, summarize_segments
from memory.topology.tree import TreeBuildResult, build_tree

DEFAULT_PARAMS: Dict[str, Any] = {
    "idle_seconds": 1800.0,
    "max_turns": 40,
    "max_chars": 8000,
}

COMPARISON_PARAMS: List[Dict[str, Any]] = [
    {"idle_seconds": 1800.0, "max_turns": 30, "max_chars": 8000},
    {"idle_seconds": 1800.0, "max_turns": 40, "max_chars": 8000},
]


def _conversations(events: Iterable[Any]) -> Dict[str, List[Any]]:
    grouped: Dict[str, List[Any]] = defaultdict(list)
    for item in events:
        event = getattr(item, "normalized", None) or item
        grouped[event.conversation_id].append(event)
    return dict(grouped)


def _leaves(tree: TreeBuildResult) -> List[str]:
    parents = {node.parent_id for node in tree.nodes.values() if node.parent_id}
    leaves = [node_id for node_id in tree.nodes if node_id not in parents]
    return sorted(leaves)


def replay_topology(
    events: Iterable[Any],
    *,
    params: Mapping[str, Any] = DEFAULT_PARAMS,
) -> Dict[str, Any]:
    grouped = _conversations(events)
    trees: List[TreeBuildResult] = [
        build_tree(items, conversation_id=conversation_id)
        for conversation_id, items in sorted(grouped.items())
    ]
    status_counts: Counter = Counter(tree.topology_status for tree in trees)
    reason_counts: Counter = Counter()
    for tree in trees:
        for reason in tree.reasons:
            reason_counts[reason.split(" ")[0] if reason else "unknown"] += 1

    idle_gaps: List[float] = []
    segments_all: List[Any] = []
    pure_social = 0
    path_count = 0
    for tree in trees:
        conversation_events = grouped.get(tree.conversation_id, [])
        for leaf in _leaves(tree) or tree.roots:
            wanted = set(tree.path_event_ids(leaf))
            path = [event for event in conversation_events if event.event_id in wanted]
            if not path:
                continue
            path_count += 1
            turns = [turn for turn in group_turns(path) if turn.eligible]
            for previous, current in zip(turns, turns[1:]):
                idle_gaps.append(max(0.0, current.started_at - previous.ended_at))
            segments = build_segments(
                path,
                tree_id=tree.tree_id,
                continuity_id=path[0].continuity_id if path else "",
                idle_seconds=float(params.get("idle_seconds") or 1800.0),
                max_turns=int(params.get("max_turns") or 40),
                max_chars=int(params.get("max_chars") or 8000),
                topology_status=tree.topology_status,
            )
            segments_all.extend(segments)
            if turns and all(turn.content_length < 20 for turn in turns):
                pure_social += 1

    return {
        "params": dict(params),
        "trees": len(trees),
        "topology_status": dict(sorted(status_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "paths": path_count,
        "segments": summarize_segments(segments_all),
        "idle_seconds": _quantiles(idle_gaps),
        "pure_social_paths": pure_social,
        "pure_social_rate": round(pure_social / path_count, 4) if path_count else None,
        "unreconstructable_trees": status_counts.get("partial", 0) + status_counts.get("unknown", 0),
        "late_event_pending_nodes": sum(len(tree.pending) for tree in trees),
        "unknown_events": sum(len(tree.unknown_event_ids) for tree in trees),
    }


def _quantiles(values: Sequence[float]) -> Dict[str, Any]:
    if not values:
        return {"count": 0, "p50": None, "p90": None, "max": None}
    ordered = sorted(values)

    def pick(ratio: float) -> float:
        return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * ratio))], 1)

    return {"count": len(ordered), "p50": pick(0.5), "p90": pick(0.9), "max": pick(1.0)}


def compare_params(events: Iterable[Any]) -> List[Dict[str, Any]]:
    """同一事件集在不同候选参数下的段数/轮数对照。"""
    items = list(events)
    results: List[Dict[str, Any]] = []
    for params in COMPARISON_PARAMS:
        report = replay_topology(items, params=params)
        results.append(
            {
                "params": dict(params),
                "segment_count": report["segments"]["segment_count"],
                "turn_counts": report["segments"]["turn_counts"],
                "char_counts": report["segments"]["char_counts"],
            }
        )
    return results
