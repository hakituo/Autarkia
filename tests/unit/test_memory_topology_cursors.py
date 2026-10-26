"""按会话持久化的分支游标（v3 E10）。

conftest 已把游标目录指到临时目录、关掉覆盖层兜底。
"""

from __future__ import annotations

from core.agents.chat_agent_components.message_branch import (
    reset_request_branch_metadata,
    set_request_branch_metadata,
)
from core.services.chat_history_store import ChatHistoryStore
from memory.topology import cursors, read_gate
from memory.topology.memory_gate import build_memory_visibility
from memory.topology.read_gate import filter_raw_events
from memory.topology.tree_registry import get_tree_registry

CONV = "web_role_aveline"


def _event(node, parent, ts):
    return {
        "event_id": f"evt-{node}",
        "conversation_id": CONV,
        "role": "user",
        "content": f"正文-{node}",
        "timestamp": ts,
        "event_type": "chat_message",
        "client_node_id": node,
        "parent_node_id": parent,
    }


# root → a → {b, c}
EVENTS = [_event("root", "", 1.0), _event("a", "root", 2.0), _event("b", "a", 3.0), _event("c", "a", 4.0)]


def _ids(events):
    return sorted(item["event_id"] for item in events)


def test_written_turn_advances_cursor_and_switch_is_labelled(monkeypatch):
    monkeypatch.setattr(read_gate, "_default_tree_reader", lambda _cid: list(EVENTS[:2]))
    get_tree_registry().tree(CONV)  # 已加载，切线判断能用上树
    first = cursors.advance_cursors([EVENTS[2]])
    assert first[CONV]["node_id"] == "b" and first[CONV]["reason"] == cursors.REASON_TURN
    assert cursors.advance_cursors([EVENTS[2]]) == {}  # 位置没变不写
    get_tree_registry().on_append([EVENTS[2], EVENTS[3]])
    switched = cursors.advance_cursors([EVENTS[3]])
    assert switched[CONV]["reason"] == cursors.REASON_SWITCH
    assert cursors.cursor_for(CONV) == "c"


def test_read_gate_without_request_path_uses_cursor(monkeypatch):
    monkeypatch.setattr(read_gate, "_default_tree_reader", lambda _cid: list(EVENTS))
    before = filter_raw_events(EVENTS, conversation_id="", branch_scope={})
    assert len(before.events) == 4  # 没有任何 anchor：兼容放行

    cursors.advance_cursors([EVENTS[2]])  # 当前在 b 线
    after = filter_raw_events(EVENTS, conversation_id="", branch_scope={})
    assert _ids(after.events) == ["evt-a", "evt-b", "evt-root"]


def test_request_path_still_wins_over_cursor(monkeypatch):
    monkeypatch.setattr(read_gate, "_default_tree_reader", lambda _cid: list(EVENTS))
    cursors.advance_cursors([EVENTS[2]])
    scope = {"allowed_message_ids": {"root", "a", "c"}, "not_after_ts": None, "conversation_id": CONV}
    outcome = filter_raw_events(EVENTS, conversation_id=CONV, branch_scope=scope)
    assert _ids(outcome.events) == ["evt-a", "evt-c", "evt-root"]


def test_memory_gate_uses_cursor_without_request(monkeypatch):
    monkeypatch.setattr(read_gate, "_default_tree_reader", lambda _cid: list(EVENTS))
    cursors.advance_cursors([EVENTS[3]])  # 当前在 c 线

    def memory(memory_id, event_id):
        return {"id": memory_id, "timestamp": 1.0, "metadata": {"event_ref": {"event_id": event_id, "conversation_id": CONV}}}

    gate = build_memory_visibility(branch_scope=None)
    assert gate.is_visible(memory("m-c", "evt-c"))
    assert not gate.is_visible(memory("m-b", "evt-b"))


def test_overlay_active_leaf_seeds_missing_cursor(monkeypatch):
    monkeypatch.setattr(cursors, "load_overlay", lambda _cid, _scope: {"active_leaf": "b"})
    assert cursors.cursor_for(CONV) == "b"
    cursors.advance_cursors([EVENTS[3]])
    assert cursors.cursor_for(CONV) == "c"  # 一旦有真实游标就不再用导出值


def test_store_write_moves_cursor(tmp_path):
    store = ChatHistoryStore(base_dir=tmp_path)
    token = set_request_branch_metadata(
        {"user_message_id": "u7", "assistant_message_id": "a7", "assistant_parent_id": "u7"}
    )
    try:
        store.append_event(conversation_id=CONV, role="user", content="你好", message_id="a7", event_type="chat_message")
        store.append_event(conversation_id=CONV, role="assistant", content="在", message_id="a7", event_type="chat_reply")
    finally:
        reset_request_branch_metadata(token)
    assert cursors.cursor_for(CONV) == "a7"
