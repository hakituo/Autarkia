"""常驻消息树：增量挂节点与全量重建结果一致（v3 D6 运行时）。"""

from __future__ import annotations

import random

from memory.topology.tree import build_tree
from memory.topology.tree_registry import TreeRegistry, normalize_payload

CONV = "web_role_aveline"


def _event(node, parent, ts, *, variant_of=""):
    payload = {
        "event_id": f"evt-{node}",
        "conversation_id": CONV,
        "role": "user",
        "content": node,
        "timestamp": ts,
        "event_type": "chat_message",
        "client_node_id": node,
        "parent_node_id": parent,
    }
    if variant_of:
        payload["variant_of_node_id"] = variant_of
    return payload


def _history():
    return [
        _event("root", "", 1.0),
        _event("a", "root", 2.0),
        _event("b", "a", 3.0),
        _event("b2", "a", 4.0, variant_of="b"),
        _event("c", "b2", 5.0),
        {"event_id": "legacy", "conversation_id": CONV, "role": "user", "content": "旧", "timestamp": 0.5},
    ]


def _full_hash(events):
    return build_tree([normalize_payload(item) for item in events], conversation_id=CONV).canonical_hash()


def test_incremental_appends_match_full_rebuild():
    events = _history()
    registry = TreeRegistry(reader=lambda _cid: events[:2])
    registry.tree(CONV)
    registry.on_append(events[2:])
    assert registry.tree(CONV).canonical_hash() == _full_hash(events)
    assert registry.full_loads == 1


def test_out_of_order_appends_still_converge():
    events = _history()
    shuffled = events[2:]
    random.Random(3).shuffle(shuffled)
    registry = TreeRegistry(reader=lambda _cid: events[:2])
    registry.tree(CONV)
    registry.on_append(shuffled)  # child 可能先于 parent 到达
    tree = registry.tree(CONV)
    assert not tree.pending
    assert tree.canonical_hash() == _full_hash(events)


def test_reads_reuse_snapshot_until_next_write():
    calls = []
    registry = TreeRegistry(reader=lambda cid: calls.append(cid) or _history()[:3])
    first = registry.tree(CONV)
    assert registry.tree(CONV) is first
    registry.on_append([_event("x", "b", 9.0)])
    assert "x" in registry.tree(CONV).nodes
    assert calls == [CONV]


def test_unloaded_conversation_is_not_built_by_writes():
    registry = TreeRegistry(reader=lambda _cid: [])
    registry.on_append([_event("root", "", 1.0)])
    assert not registry.loaded(CONV)


def test_forget_drops_tree_and_reloads_on_next_read():
    rows = [_event("root", "", 1.0)]
    registry = TreeRegistry(reader=lambda _cid: list(rows))
    registry.tree(CONV)
    registry.forget(CONV)
    rows.append(_event("a", "root", 2.0))
    assert set(registry.tree(CONV).nodes) == {"root", "a"}
    assert registry.full_loads == 2


def test_refresh_window_rebuilds_for_out_of_process_writes():
    rows = [_event("root", "", 1.0)]
    registry = TreeRegistry(reader=lambda _cid: list(rows), refresh_seconds=-1)
    registry.tree(CONV)
    rows.append(_event("a", "root", 2.0))
    # refresh_seconds<=0 关闭兜底刷新：其他进程直写的节点不会被看到
    assert set(registry.tree(CONV).nodes) == {"root"}


def test_legacy_thought_without_node_maps_to_its_reply_node():
    thought = {"event_id": "t1", "conversation_id": CONV, "role": "system", "event_type": "chat_thought",
               "content": "想", "timestamp": 3.5, "message_id": "b"}
    registry = TreeRegistry(reader=lambda _cid: _history()[:3] + [thought])
    _, index = registry.snapshot(CONV)
    assert index["t1"] == "b"
