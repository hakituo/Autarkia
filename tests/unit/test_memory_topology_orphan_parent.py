"""回复主动消息时 parent 未知：游标不得跳到孤立根，无请求路径的读不隐藏主线（2026-10-26）。

conftest 已把游标目录指到临时目录、关掉覆盖层兜底。
"""

from __future__ import annotations

import asyncio
import json
import random
from types import SimpleNamespace

from memory.topology import cursors, read_gate
from memory.topology.anchors import AnchorStore
from memory.topology.events import enrich_payload, normalize_event
from memory.topology.read_gate import filter_raw_events
from memory.topology.tree import build_tree
from memory.topology.tree_registry import get_tree_registry

CONV = "web_role_aveline"


def _event(node, parent, ts, role="user", event_id=""):
    return {
        "event_id": event_id or f"evt-{node}",
        "conversation_id": CONV,
        "role": role,
        "content": f"正文-{node}",
        "timestamp": ts,
        "event_type": "chat_message",
        "client_node_id": node,
        "parent_node_id": parent,
    }


# 主线 root → a → b（b 是游标）
MAIN = [_event("root", "", 1.0), _event("a", "root", 2.0, "assistant"), _event("b", "a", 3.0)]
# 旧写法的主动消息：没有节点；Android 给它的本地节点 ID 服务端不认识
PROACTIVE_LEGACY = {
    "event_id": "evt-proactive",
    "conversation_id": CONV,
    "role": "assistant",
    "content": "主动消息",
    "timestamp": 4.0,
    "event_type": "proactive_message",
}
REPLY = _event("bg-3", "android-local-proactive", 5.0)
REPLY_ANSWER = _event("bg-4", "bg-3", 5.1, "assistant")


def _use_events(monkeypatch, events):
    monkeypatch.setattr(read_gate, "_default_tree_reader", lambda _cid: list(events))


def _hidden(events):
    outcome = filter_raw_events(events, conversation_id=CONV, branch_scope={})
    return outcome.hidden, outcome.reasons


def _start_on_main(monkeypatch):
    _use_events(monkeypatch, MAIN)
    get_tree_registry().tree(CONV)
    cursors.advance_cursors([MAIN[-1]])
    assert cursors.cursor_for(CONV) == "b"


def test_unknown_parent_reply_is_grafted_not_switched(monkeypatch):
    _start_on_main(monkeypatch)
    written = [PROACTIVE_LEGACY, REPLY, REPLY_ANSWER]
    get_tree_registry().on_append(written)
    records = cursors.advance_cursors(written)

    assert records[CONV]["reason"] == cursors.REASON_GRAFT  # 不是 branch_switch
    assert cursors.grafts_for(CONV) == {"bg-3": "b"}
    tree = get_tree_registry().tree(CONV)
    assert tree.roots == ["root"] and tree.pending == []
    assert tree.ancestors("bg-4") == ["root", "a", "b", "bg-3", "bg-4"]

    all_events = MAIN + written
    _use_events(monkeypatch, all_events)
    hidden, reasons = _hidden(all_events)
    assert hidden == 0, reasons  # 主线和新回复都在游标路径上


def test_later_turns_on_grafted_chain_keep_advancing(monkeypatch):
    _start_on_main(monkeypatch)
    get_tree_registry().on_append([REPLY, REPLY_ANSWER])
    cursors.advance_cursors([REPLY, REPLY_ANSWER])
    nxt = _event("bg-5", "bg-4", 6.0)
    get_tree_registry().on_append([nxt])
    assert cursors.advance_cursors([nxt])[CONV]["reason"] == cursors.REASON_TURN
    assert cursors.cursor_for(CONV) == "bg-5"


def test_real_parent_arriving_later_wins_over_graft(monkeypatch):
    _start_on_main(monkeypatch)
    get_tree_registry().on_append([REPLY])
    cursors.advance_cursors([REPLY])
    late = _event("android-local-proactive", "a", 4.5, "assistant")
    get_tree_registry().on_append([late])
    tree = get_tree_registry().tree(CONV)
    assert tree.nodes["bg-3"].parent_id == "android-local-proactive"
    assert "bg-3" not in tree.inferred_parents


def test_orphan_without_grounded_previous_holds_cursor(monkeypatch):
    _use_events(monkeypatch, MAIN + [REPLY])
    get_tree_registry().tree(CONV)
    cursors._store("aveline").set(CONV, "ghost-node", reason="test")  # 旧游标不在树上
    cursors.reset_cursor_cache()
    assert cursors.advance_cursors([REPLY]) == {}
    assert cursors.cursor_for(CONV) == "ghost-node"
    log = cursors._store("aveline").events_path.read_text(encoding="utf-8")
    assert '"anchor_held"' in log


def test_read_side_ignores_cursor_on_orphan_chain(monkeypatch):
    events = MAIN + [REPLY, REPLY_ANSWER]
    _use_events(monkeypatch, events)
    AnchorStore("aveline", base_dir=cursors.base_dir_for("aveline")).set(CONV, "bg-4")  # 旧版写下的坏游标
    cursors.reset_cursor_cache()
    hidden, reasons = _hidden(events)
    assert reasons.get("not_on_anchor_path", 0) == 0, reasons
    assert hidden == 0


def test_proactive_node_fields_follow_cursor(monkeypatch):
    _start_on_main(monkeypatch)
    assert cursors.proactive_node_fields(CONV, "") == {}
    assert cursors.proactive_node_fields(CONV, "ws-1") == {"client_message_id": "ws-1", "parent_id": "b"}
    assert cursors.proactive_node_fields("web_role_lin", "ws-1") == {}  # 没有游标不建新根


def test_proactive_with_node_then_reply_is_plain_turn(monkeypatch):
    _start_on_main(monkeypatch)
    proactive = dict(PROACTIVE_LEGACY, metadata=cursors.proactive_node_fields(CONV, "ws-1"))
    proactive.update(enrich_payload(proactive))  # 与 ChatHistoryStore 落盘前的补字段一致
    reply = _event("bg-3", "ws-1-2", 5.0)  # Android 把主动消息拆成三个气泡，回复挂最后一个
    get_tree_registry().on_append([proactive])
    assert cursors.advance_cursors([proactive])[CONV]["reason"] == cursors.REASON_TURN
    get_tree_registry().on_append([reply])
    assert cursors.advance_cursors([reply])[CONV]["reason"] == cursors.REASON_TURN
    tree = get_tree_registry().tree(CONV)
    assert tree.ancestors("bg-3") == ["root", "a", "b", "ws-1", "bg-3"]
    assert tree.inferred_parents == {"bg-3": "segment_alias"}
    assert cursors.grafts_for(CONV) == {}


def test_segment_alias_is_order_independent():
    proactive = dict(PROACTIVE_LEGACY, metadata={"client_message_id": "ws-1", "parent_id": "b"})
    payloads = MAIN + [proactive, _event("bg-3", "ws-1-2", 5.0)]
    events = [normalize_event(item) for item in payloads]
    hashes = set()
    for seed in range(5):
        random.Random(seed).shuffle(events)
        tree = build_tree(events, conversation_id=CONV)
        hashes.add(tree.canonical_hash())
        assert tree.nodes["bg-3"].parent_id == "ws-1"
    assert len(hashes) == 1


def test_segment_alias_only_for_assistant_nodes():
    events = [normalize_event(item) for item in MAIN + [_event("x", "b-1", 5.0)]]
    tree = build_tree(events, conversation_id=CONV)  # b 是用户节点，不是多气泡
    assert tree.pending == ["x"] and not tree.is_grounded("x")


def test_append_proactive_message_writes_pushed_id_as_node(monkeypatch):
    import core.services.chat_history_store as chs
    import memory.weighted_memory_manager as wmm
    from core.services.aveline import proactive_messaging

    _start_on_main(monkeypatch)
    captured = []
    store = SimpleNamespace(append_event=lambda **kwargs: captured.append(kwargs))
    monkeypatch.setattr(chs, "get_chat_history_store", lambda: store)
    monkeypatch.setattr(wmm, "get_weighted_memory_manager", lambda _cid: None)
    asyncio.run(
        proactive_messaging.append_proactive_message(
            None, conversation_id=CONV, content="早", client_message_id="ws-9"
        )
    )
    (written,) = captured
    assert written["message_id"] == "ws-9"
    assert written["metadata"]["client_message_id"] == "ws-9"
    assert written["metadata"]["parent_id"] == "b"
    json.dumps(written["metadata"])  # 落盘前可序列化


def test_multi_root_reason_is_reported():
    events = [normalize_event(item) for item in MAIN + [_event("other", "", 9.0)]]
    tree = build_tree(events, conversation_id=CONV)
    assert any("个根节点" in reason for reason in tree.reasons)
