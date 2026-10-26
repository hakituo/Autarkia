"""统一可见性谓词：亲兄弟不互见、缺 anchor 不放行、shared 只豁免 note 自身。"""

from __future__ import annotations

from dataclasses import replace

from memory.topology.events import normalize_event
from memory.topology.read_context import (
    MODE_COMPAT,
    build_read_context,
    event_visibility_reason,
    filter_visible_events,
    note_visibility_reason,
)
from memory.topology.tree import build_tree


def _ev(node_id, parent="", *, event_id="", ts=1.0, namespace="aveline"):
    return normalize_event(
        {
            "event_id": event_id or f"evt-{node_id}",
            "conversation_id": "shared__scope__aveline",
            "role": "user",
            "content": "正文",
            "timestamp": ts,
            "event_type": "chat_message",
            "client_node_id": node_id,
            "parent_node_id": parent,
            "namespace": namespace,
            "perspective_role": namespace,
        },
        storage_scope=namespace,
    )


def _fixture():
    events = [
        _ev("root", event_id="e-root", ts=1.0),
        _ev("a", "root", event_id="e-a", ts=2.0),
        _ev("b", "a", event_id="e-b", ts=3.0),
        _ev("c", "a", event_id="e-c", ts=4.0),
    ]
    tree = build_tree(events, conversation_id="shared__scope__aveline")
    tagged = [replace(event, tree_id=tree.tree_id) for event in events]
    by_id = {event.event_id: event for event in tagged}
    return tree, tagged, by_id


def _ctx(tree, anchor="b", **kwargs):
    defaults = {
        "namespace": "aveline",
        "perspective_role": "aveline",
        "continuity_id": "continuity:scope:aveline",
        "anchors_by_tree": {tree.tree_id: tree.nodes[anchor].node_id},
    }
    defaults.update(kwargs)
    return build_read_context(**defaults)


def test_shared_ancestors_visible_sibling_hidden():
    tree, events, _ = _fixture()
    ctx = _ctx(tree)

    reasons = {event.event_id: event_visibility_reason(ctx, event, {tree.tree_id: tree}) for event in events}

    assert reasons["e-root"] is None
    assert reasons["e-a"] is None
    assert reasons["e-b"] is None
    assert reasons["e-c"] == "not_on_anchor_path"


def test_missing_anchor_fails_closed():
    tree, events, _ = _fixture()
    ctx = build_read_context(
        namespace="aveline",
        allowed_trees=[tree.tree_id],
        anchors_by_tree={},
    )

    reasons = {
        event_visibility_reason(ctx, event, {tree.tree_id: tree}) for event in events
    }

    assert reasons == {"anchor_missing"}


def test_tree_not_in_allowed_set_is_denied():
    tree, events, _ = _fixture()
    ctx = _ctx(tree)
    ctx = replace(ctx, allowed_trees=frozenset({"other-tree"}))

    assert event_visibility_reason(ctx, events[-1], {tree.tree_id: tree}) == "tree_not_allowed"


def test_namespace_and_perspective_are_hard_filters():
    tree, events, _ = _fixture()
    other_ns = build_read_context(
        namespace="ling",
        anchors_by_tree={tree.tree_id: "b"},
    )
    other_view = build_read_context(
        namespace="aveline",
        perspective_role="ling",
        anchors_by_tree={tree.tree_id: "b"},
    )

    assert event_visibility_reason(other_ns, events[0], {tree.tree_id: tree}) == "namespace_mismatch"
    assert (
        event_visibility_reason(other_view, events[0], {tree.tree_id: tree})
        == "perspective_mismatch"
    )


def test_as_of_excludes_later_recorded_events():
    tree, events, _ = _fixture()
    events[0] = replace(events[0], recorded_at=500.0)
    ctx = _ctx(tree, as_of=100.0)

    assert event_visibility_reason(ctx, events[0], {tree.tree_id: tree}) == "as_of_excluded"


def test_legacy_unknown_is_compat_only():
    legacy = normalize_event(
        {
            "event_id": "legacy-1",
            "conversation_id": "shared__scope__aveline",
            "role": "user",
            "content": "老数据",
            "timestamp": 1.0,
            "namespace": "aveline",
            "perspective_role": "aveline",
        }
    )
    strict = build_read_context(namespace="aveline")
    compat = build_read_context(namespace="aveline", mode=MODE_COMPAT)

    assert event_visibility_reason(strict, legacy, {}) == "legacy_unknown"
    assert event_visibility_reason(compat, legacy, {}) is None


def test_note_from_sibling_source_is_hidden():
    tree, _, by_id = _fixture()
    ctx = _ctx(tree)
    note = {
        "visibility": "tree_local",
        "namespace": "aveline",
        "source_event_ids": ["e-c"],
    }

    assert (
        note_visibility_reason(ctx, note, by_id, {tree.tree_id: tree})
        == "source_not_on_anchor_path"
    )


def test_note_on_current_path_is_visible():
    tree, _, by_id = _fixture()
    ctx = _ctx(tree)
    note = {
        "visibility": "tree_local",
        "namespace": "aveline",
        "source_event_ids": ["e-a", "e-b"],
    }

    assert note_visibility_reason(ctx, note, by_id, {tree.tree_id: tree}) is None


def test_shared_note_is_exempt_but_its_sources_are_not():
    tree, _, by_id = _fixture()
    ctx = _ctx(tree)
    shared_note = {
        "visibility": "namespace_shared",
        "namespace": "aveline",
        "source_event_ids": ["e-c"],
    }

    # note 本身豁免 tree 路径
    assert note_visibility_reason(ctx, shared_note, by_id, {tree.tree_id: tree}) is None
    # 展开 source 时仍按 raw 路径复核
    assert (
        event_visibility_reason(ctx, by_id["e-c"], {tree.tree_id: tree})
        == "not_on_anchor_path"
    )


def test_note_without_sources_is_unresolvable():
    tree, _, by_id = _fixture()
    ctx = _ctx(tree)

    assert (
        note_visibility_reason(
            ctx, {"visibility": "tree_local", "namespace": "aveline"}, by_id, {tree.tree_id: tree}
        )
        == "source_unresolvable"
    )


def test_continuity_local_note_requires_same_continuity():
    tree, _, by_id = _fixture()
    ctx = _ctx(tree, continuity_id="continuity:scope:aveline")
    note = {
        "visibility": "continuity_local",
        "namespace": "aveline",
        "continuity_id": "continuity:scope:ling",
        "source_event_ids": ["e-a"],
    }

    assert (
        note_visibility_reason(ctx, note, by_id, {tree.tree_id: tree})
        == "continuity_mismatch"
    )


def test_filter_visible_events_keeps_only_anchor_path():
    tree, events, _ = _fixture()
    ctx = _ctx(tree)

    visible = filter_visible_events(ctx, events, {tree.tree_id: tree})

    assert [event.event_id for event in visible] == ["e-root", "e-a", "e-b"]
