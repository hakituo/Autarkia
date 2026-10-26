"""Room 回填的旁挂拓扑覆盖层：写入、叠加建树、读路径隔离与回退。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from memory.maintenance.topology_backfill import build_plan, load_room_sessions
from memory.maintenance.topology_backfill.apply import apply_plan
from memory.topology import overlay as overlay_module
from memory.topology import tree_registry
from memory.topology.memory_gate import memory_conversation_id
from memory.topology.read_gate import filter_raw_events

CID = "web_role_test"
BASE_MS = 1_800_000_000_000
BASE_S = BASE_MS // 1000


def _db(path: Path, rows) -> Path:
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE messages (id TEXT PRIMARY KEY, sessionId TEXT, parentId TEXT, text TEXT, "
        "timestamp INTEGER, isUser INTEGER, variantIndex INTEGER, isActiveVariant INTEGER, "
        "messageType TEXT)"
    )
    con.executemany("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return path


def _node(node_id, parent, text, offset_ms, *, user, variant=0, active=True):
    return (node_id, CID, parent, text, BASE_MS + offset_ms, int(user), variant, int(active), "text")


def _event(event_id, message_id, role, content, offset_s):
    return {
        "event_id": event_id,
        "conversation_id": CID,
        "message_id": message_id,
        "role": role,
        "event_type": "chat_message" if role == "user" else "chat_reply",
        "content": content,
        "timestamp": BASE_S + offset_s,
        "storage_scope": "test_scope",
    }


# u1 → {a1（被重新生成掉）, a2（当前）} → u2 → a3；e3 是 u1 的重复提交
ROWS = [
    _node("u1", None, "你好", 0, user=True),
    _node("a1", "u1", "版本一", 1000, user=False, variant=0, active=False),
    _node("a2", "u1", "版本二", 2000, user=False, variant=1),
    _node("u2", "a2", "继续聊", 3000, user=True),
    _node("a3", "u2", "好的", 4000, user=False),
]
EVENTS = [
    _event("e1", "m1", "user", "你好", 0),
    _event("e2", "m1", "assistant", "版本一。", 1),
    _event("e3", "m2", "user", "你好", 2),
    _event("e4", "m2", "assistant", "版本二。", 2),
    _event("e5", "m3", "user", "继续聊", 3),
    _event("e6", "m3", "assistant", "好的。", 4),
    _event("legacy", "m0", "user", "手机上没有的旧消息", -100000),
]


@pytest.fixture()
def overlay_dir(tmp_path, monkeypatch):
    target = tmp_path / "overlays"
    monkeypatch.setattr(
        overlay_module, "overlay_path", lambda cid, _scope: target / f"{cid}.json"
    )
    overlay_module.clear_overlay_cache()
    registry = tree_registry.TreeRegistry(
        reader=lambda _cid: [dict(item) for item in EVENTS],
        overlay_loader=overlay_module.load_overlay,
    )
    monkeypatch.setattr(tree_registry, "get_tree_registry", lambda: registry)
    yield target
    overlay_module.clear_overlay_cache()


def _plan(tmp_path, rows=ROWS):
    sessions = load_room_sessions(_db(tmp_path / "aveline_database", rows))
    return build_plan(sessions, {CID: [dict(item) for item in EVENTS]}, {CID: ["test_scope"]})


def _visible(path_ids):
    scope = {"allowed_message_ids": set(path_ids), "not_after_ts": None, "conversation_id": CID}
    outcome = filter_raw_events(EVENTS, conversation_id=CID, branch_scope=scope)
    return sorted(item["event_id"] for item in outcome.events), outcome


def test_dry_run_writes_nothing(tmp_path, overlay_dir):
    report = apply_plan(_plan(tmp_path), dry_run=True)
    assert report.totals()["written"] == 0
    assert not overlay_dir.exists()


def test_applied_overlay_hides_regenerated_branch_on_read_path(tmp_path, overlay_dir):
    report = apply_plan(_plan(tmp_path), dry_run=False)
    assert report.totals()["written"] == 1
    assert report.results[0].active_leaf == "a3"

    visible, outcome = _visible({"u1", "a2", "u2", "a3"})
    # e2 是被重新生成掉的 a1；e3 是 u1 的重复提交（经别名索引认回 u1，可见）
    assert "e2" not in visible
    assert {"e1", "e3", "e4", "e5", "e6"} <= set(visible)
    assert "legacy" in visible  # 窗口外旧消息：仍按兼容模式放行
    assert outcome.reasons.get("not_on_anchor_path") == 1


def test_switching_to_old_branch_shows_it_and_hides_new(tmp_path, overlay_dir):
    apply_plan(_plan(tmp_path), dry_run=False)
    visible, _ = _visible({"u1", "a1"})
    assert "e2" in visible and "e4" not in visible and "e6" not in visible


def test_deleting_overlay_fully_reverts(tmp_path, overlay_dir, monkeypatch):
    apply_plan(_plan(tmp_path), dry_run=False)
    for path in overlay_dir.glob("*.json"):
        path.unlink()
    overlay_module.clear_overlay_cache()
    fresh = tree_registry.TreeRegistry(
        reader=lambda _cid: [dict(item) for item in EVENTS],
        overlay_loader=overlay_module.load_overlay,
    )
    monkeypatch.setattr(tree_registry, "get_tree_registry", lambda: fresh)
    visible, outcome = _visible({"u1", "a2", "u2", "a3"})
    assert len(visible) == len(EVENTS)
    assert "not_on_anchor_path" not in outcome.reasons


def test_structural_nodes_keep_chain_connected(tmp_path, overlay_dir):
    rows = ROWS + [_node("a3b", "a3", "第二个气泡", 4500, user=False)]
    rows += [_node("u3", "a3b", "下一句", 5000, user=True)]
    events = EVENTS + [_event("e7", "m4", "user", "下一句", 5)]
    sessions = load_room_sessions(_db(tmp_path / "aveline_database", rows))
    plan = build_plan(sessions, {CID: events}, {CID: ["test_scope"]})
    apply_plan(plan, dry_run=False)
    registry = tree_registry.TreeRegistry(
        reader=lambda _cid: [dict(item) for item in events],
        overlay_loader=overlay_module.load_overlay,
    )
    tree = registry.tree(CID)
    # a3b 没有服务端事件，作为结构节点入树；u3 不再挂成待定
    assert "a3b" in tree.nodes and not tree.pending
    assert tree.ancestors("u3")[-3:] == ["a3", "a3b", "u3"]


def test_medium_confidence_excluded_by_default(tmp_path, overlay_dir):
    plan = _plan(tmp_path)
    decision = next(item for item in plan.iter_decisions() if item.event_id == "e6")
    decision.confidence = "medium"
    report = apply_plan(plan, dry_run=False)
    assert report.results[0].skipped_low_confidence == 1
    stored = overlay_module.load_overlay(CID, "test_scope")
    assert "e6" not in stored["events"]


def test_active_path_falls_back_when_no_variant_is_active(tmp_path):
    rows = [
        _node("u1", None, "你好", 0, user=True),
        _node("a1", "u1", "版本一", 1000, user=False, variant=0, active=False),
        _node("a2", "u1", "版本二", 2000, user=False, variant=1, active=False),
        _node("u2", "a1", "后来接着版本一聊", 9000, user=True),
    ]
    session = load_room_sessions(_db(tmp_path / "aveline_database", rows))[CID]
    assert session.active_path == ["u1", "a1", "u2"]
    assert session.integrity["active_path_fallbacks"] == 1


def test_memory_conversation_falls_back_to_event_ref():
    memory = {"metadata": {"event_ref": {"event_id": "e1", "conversation_id": CID}}}
    assert memory_conversation_id(memory) == CID
    assert memory_conversation_id({"metadata": {"conversation_id": "x", "event_ref": memory["metadata"]["event_ref"]}}) == "x"
