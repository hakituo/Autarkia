"""逐 tree 游标：请求优先、可恢复、切线只改游标不改历史。"""

from __future__ import annotations

import json

from memory.topology.anchors import (
    AnchorStore,
    bound_anchors,
    get_request_anchors,
    resolve_anchors_by_tree,
    set_request_anchors,
    reset_request_anchors,
)


def test_store_persists_anchor_and_appends_event(tmp_path):
    store = AnchorStore("aveline", base_dir=tmp_path)
    store.set("tree-1", "node-a", reason="switch", changed_at=100.0)
    store.set("tree-1", "node-b", reason="switch", changed_at=200.0)

    reloaded = AnchorStore("aveline", base_dir=tmp_path)
    assert reloaded.get("tree-1") == "node-b"

    lines = [
        json.loads(line)
        for line in (tmp_path / "anchor_events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [item["node_id"] for item in lines] == ["node-a", "node-b"]
    assert lines[1]["previous"] == "node-a"
    assert lines[1]["type"] == "anchor_changed"


def test_switch_back_to_old_branch_only_changes_cursor(tmp_path):
    store = AnchorStore("aveline", base_dir=tmp_path)
    store.set("tree-1", "branch-b", changed_at=1.0)
    store.set("tree-1", "branch-a", changed_at=2.0)

    assert store.get("tree-1") == "branch-a"
    events = (tmp_path / "anchor_events.jsonl").read_text(encoding="utf-8").splitlines()
    # 两条切线事件都在：回退只改游标，不删除历史
    assert len([line for line in events if line.strip()]) == 2


def test_resolve_uses_explicit_before_stored(tmp_path):
    store = AnchorStore("aveline", base_dir=tmp_path)
    store.set("tree-1", "stored-node", changed_at=1.0)

    resolved = resolve_anchors_by_tree(
        ["tree-1", "tree-2"],
        explicit={"tree-1": "request-node"},
        store=store,
    )

    assert resolved["tree-1"] == "request-node"
    assert resolved["tree-2"] is None


def test_missing_anchor_is_none_not_wildcard(tmp_path):
    store = AnchorStore("aveline", base_dir=tmp_path)

    resolved = resolve_anchors_by_tree(["tree-x"], store=store)

    assert resolved == {"tree-x": None}


def test_request_context_var_returns_copy_and_resets():
    token = set_request_anchors({"tree-1": "node-1"})
    try:
        current = get_request_anchors()
        assert current == {"tree-1": "node-1"}
        current["tree-1"] = "mutated"
        assert get_request_anchors() == {"tree-1": "node-1"}
    finally:
        reset_request_anchors(token)
    assert get_request_anchors() is None


def test_bound_anchors_restores_previous_binding():
    token = set_request_anchors({"tree-1": "outer"})
    try:
        with bound_anchors({"tree-2": "inner"}):
            assert get_request_anchors() == {"tree-2": "inner"}
        assert get_request_anchors() == {"tree-1": "outer"}
    finally:
        reset_request_anchors(token)


def test_empty_anchor_value_is_rejected(tmp_path):
    store = AnchorStore("aveline", base_dir=tmp_path)

    try:
        store.set("tree-1", "  ")
    except ValueError:
        pass
    else:  # pragma: no cover - 防御性断言
        raise AssertionError("空 anchor 必须被拒绝")
