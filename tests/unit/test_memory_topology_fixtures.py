"""合成消息树 fixtures：世界线可见性、拓扑确定性、幂等与内容门控（C5 / E8）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from memory.topology.events import normalize_event
from memory.topology.read_context import (
    MODE_COMPAT,
    build_read_context,
    event_visibility_reason,
    note_visibility_reason,
)
from memory.topology.tree import build_tree

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "memory_topology" / "synthetic_trees.json"
)


def _load_cases() -> List[Dict[str, Any]]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return payload["cases"]


def _normalize(case: Dict[str, Any]) -> List[Any]:
    return [
        normalize_event(
            {
                **event,
                "conversation_id": event.get("conversation_id") or case["conversation_id"],
                "metadata": {"message_id": event.get("turn_id") or ""},
            },
            storage_scope="aveline",
            perspective_role="aveline",
        )
        for event in case["events"]
    ]


def _build(events: List[Any]) -> Dict[str, Any]:
    """按会话分组建树；一个 fixture 用例可以覆盖多个 conversation。"""
    grouped: Dict[str, List[Any]] = {}
    for event in events:
        grouped.setdefault(event.conversation_id, []).append(event)
    return {
        conversation: build_tree(items, conversation_id=conversation)
        for conversation, items in grouped.items()
    }


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: case["id"])
def test_synthetic_case(case):
    events = _normalize(case)
    expect = case["expect"]
    trees_by_conv = _build(events)
    primary_conv = events[0].conversation_id
    tree = trees_by_conv[primary_conv]
    by_id = {event.event_id: event for event in events}
    trees = {tree.tree_id: tree for tree in trees_by_conv.values()}

    if "topology_status" in expect:
        assert tree.topology_status == expect["topology_status"]
    if "conversation_count" in expect:
        assert (
            len({event.conversation_id for event in events}) == expect["conversation_count"]
        )
    if "pending_nodes" in expect:
        assert tree.pending == expect["pending_nodes"]
    if "event_count_in_tree" in expect:
        total = sum(len(node.event_ids) for node in tree.nodes.values())
        assert total == expect["event_count_in_tree"]
    if expect.get("order_independent"):
        reversed_tree = build_tree(list(reversed(events)), conversation_id=events[0].conversation_id)
        assert reversed_tree.canonical_hash() == tree.canonical_hash()
    for node_id, expected_ids in (expect.get("visible_event_ids") or {}).items():
        assert sorted(tree.visible_event_ids(node_id)) == sorted(expected_ids)
    for event_id, eligible in (expect.get("content_eligible") or {}).items():
        assert by_id[event_id].content_eligible is eligible
    pair = expect.get("continuity_equal")
    if pair:
        assert by_id[pair[0]].continuity_id == by_id[pair[1]].continuity_id

    for anchor, notes in (expect.get("note_visible") or {}).items():
        ctx = build_read_context(
            namespace="aveline",
            perspective_role="aveline",
            continuity_id=events[0].continuity_id,
            anchors_by_tree={tree.tree_id: anchor},
        )
        for note in case.get("notes") or []:
            reason = note_visibility_reason(ctx, note, by_id, trees)
            assert (reason is None) is notes[note["note_id"]], (
                f"{note['note_id']} 期望可见={notes[note['note_id']]}，实际原因={reason}"
            )

    if "strict_visible" in expect:
        strict = build_read_context(namespace="aveline")
        compat = build_read_context(namespace="aveline", mode=MODE_COMPAT)
        event = events[0]
        assert (event_visibility_reason(strict, event, {}) is None) is expect["strict_visible"]
        assert (event_visibility_reason(compat, event, {}) is None) is expect["compat_visible"]


def test_fixture_file_only_contains_synthetic_content():
    """仓库内只放合成 fixtures：不允许出现本机绝对路径或真实数据目录名。"""
    text = FIXTURE_PATH.read_text(encoding="utf-8")
    assert "companion_data" not in text
    assert "D:\\" not in text
    assert "/home/" not in text
