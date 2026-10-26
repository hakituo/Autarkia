"""关系图的世界线闸门：种子、逐跳扩展、最终返回三处都不放兄弟线（v3 E3）。

记忆本身不带客户端节点 ID（与线上数据一致），只能靠 ``event_ref`` 回到原始
事件所在的树节点判定——旧的 lineage 闸门在这种数据上完全失效。
"""

from __future__ import annotations

import threading

from core.agents.chat_agent_components.message_branch import (
    reset_chat_history_branch_scope,
    set_chat_history_branch_scope,
)
from memory.core.relation_graph import get_relation_cluster, rerank_with_relation_graph
from memory.topology import read_gate
from memory.topology.memory_gate import build_memory_visibility
from memory.topology.read_context import MODE_STRICT

CONV = "web_role_aveline"


class _Manager:
    def __init__(self, memories):
        self.weighted_memories = memories
        self.lock = threading.RLock()
        self._use_rw_lock = False


def _event(node: str, parent: str, ts: float, role: str = "user") -> dict:
    return {
        "event_id": f"evt-{node}",
        "conversation_id": CONV,
        "role": role,
        "content": f"正文-{node}",
        "timestamp": ts,
        "event_type": "chat_message",
        "client_node_id": node,
        "parent_node_id": parent,
    }


# root → a → {b, c}：b 与 c 是同一 parent 下的兄弟线
EVENTS = [
    _event("root", "", 1.0),
    _event("a", "root", 2.0, role="assistant"),
    _event("b", "a", 3.0),
    _event("c", "a", 4.0),
]


def _memory(memory_id, *, ts, event=None, conversation=CONV, turn="", topics=()):
    metadata = {}
    if conversation:
        metadata["conversation_id"] = conversation
    if event:
        metadata["event_ref"] = {"event_id": event}
    if turn:
        metadata["turn_id"] = turn
    return {
        "id": memory_id,
        "content": f"记忆-{memory_id}",
        "timestamp": ts,
        "weight": 5.0,
        "topics": list(topics),
        "source": "user",
        "role": "user",
        "category": "event",
        "memory_type": "dialogue",
        "status": "active",
        "scopes": ["sfw"],
        "metadata": metadata,
    }


def _manager():
    return _Manager(
        {
            "m-root": _memory("m-root", ts=1.0, event="evt-root", topics=["修电脑"]),
            # b / c 同一 turn key：图里是 0.94 的强边，旧 lineage 闸门拦不住
            "m-b": _memory("m-b", ts=3.0, event="evt-b", turn="t1"),
            "m-c": _memory("m-c", ts=4.0, event="evt-c", turn="t1", topics=["修电脑"]),
            # 只能经 m-c 到达的节点：没有会话 ID，compat 下自身可见
            "m-x": _memory("m-x", ts=4000.0, conversation="", turn="t-x", topics=["修电脑"]),
            "m-c-tail": _memory("m-c-tail", ts=4.5, event="evt-c", turn="t-x"),
            "m-other": _memory("m-other", ts=2.5, conversation="qq_private_1"),
        }
    )


def _gate(path_ids, *, mode="compat"):
    scope = {
        "allowed_message_ids": set(path_ids),
        "not_after_ts": None,
        "conversation_id": CONV,
    }
    return build_memory_visibility(mode=mode, branch_scope=scope, tree_reader=lambda _cid: EVENTS)


def _scored(manager, *ids, score=0.9):
    return [{**manager.weighted_memories[mid], "hybrid_score": score} for mid in ids]


def _ids(items):
    return [item["id"] for item in items]


def test_sibling_seed_is_dropped_before_ranking():
    manager = _manager()
    ranked = rerank_with_relation_graph(
        manager, _scored(manager, "m-c", "m-b"), limit=5, visibility=_gate({"root", "a", "b"})
    )
    assert "m-c" not in _ids(ranked)
    assert "m-b" in _ids(ranked)


def test_sibling_not_expanded_through_strong_turn_edge():
    manager = _manager()
    ungated = rerank_with_relation_graph(
        manager, _scored(manager, "m-b"), limit=5, visibility=None
    )
    assert "m-c" in _ids(ungated)  # 前提：没有闸门时强边会把兄弟线补回来

    gated = rerank_with_relation_graph(
        manager, _scored(manager, "m-b"), limit=5, visibility=_gate({"root", "a", "b"})
    )
    assert "m-c" not in _ids(gated)


def test_sibling_cannot_be_used_as_stepping_stone():
    manager = _manager()
    gated = rerank_with_relation_graph(
        manager, _scored(manager, "m-b"), limit=10, visibility=_gate({"root", "a", "b"})
    )
    assert "m-c-tail" not in _ids(gated)
    assert "m-x" not in _ids(gated)


def test_cluster_hides_sibling_and_refuses_hidden_root():
    manager = _manager()
    gate = _gate({"root", "a", "b"})
    cluster = get_relation_cluster(manager, "m-b", limit=10, max_depth=2, visibility=gate)
    assert "m-c" not in _ids(cluster)
    assert get_relation_cluster(manager, "m-c", limit=10, visibility=_gate({"root", "a", "b"})) == []


def test_switch_branch_and_back_restores_same_visible_set():
    manager = _manager()
    seeds = _scored(manager, "m-b", "m-c", "m-root")
    first = _ids(rerank_with_relation_graph(manager, seeds, limit=10, visibility=_gate({"root", "a", "b"})))
    other = _ids(rerank_with_relation_graph(manager, seeds, limit=10, visibility=_gate({"root", "a", "c"})))
    back = _ids(rerank_with_relation_graph(manager, seeds, limit=10, visibility=_gate({"root", "a", "b"})))
    assert "m-c" in other and "m-b" not in other
    assert sorted(first) == sorted(back)


def test_rollback_boundary_hides_later_memories_without_event_ref():
    manager = _Manager(
        {
            "early": _memory("early", ts=2.0),
            "late": _memory("late", ts=10.0),
            "other": _memory("other", ts=10.0, conversation="qq_private_1"),
        }
    )
    scope = {"allowed_message_ids": set(), "not_after_ts": 3.0, "conversation_id": CONV}
    gate = build_memory_visibility(branch_scope=scope, tree_reader=lambda _cid: EVENTS)
    ranked = rerank_with_relation_graph(
        manager, _scored(manager, "early", "late", "other"), limit=5, visibility=gate
    )
    assert sorted(_ids(ranked)) == ["early", "other"]
    assert gate.reasons["branch_rolled_back"] == 1


def test_strict_mode_hides_trees_without_anchor():
    manager = _manager()
    gate = _gate({"root", "a", "b"}, mode=MODE_STRICT)
    ranked = rerank_with_relation_graph(
        manager, _scored(manager, "m-other", "m-b"), limit=5, visibility=gate
    )
    assert _ids(ranked)[:1] == ["m-b"]
    assert "m-other" not in _ids(ranked)


def test_no_worldline_context_keeps_old_behaviour():
    assert build_memory_visibility(branch_scope=None, use_cursors=False) is None
    # 没有请求上下文时只剩游标判定：没有游标的会话全部放行，且不为它读树
    manager = _manager()
    gate = build_memory_visibility(branch_scope=None, tree_reader=lambda _cid: EVENTS)
    assert all(gate.is_visible(memory) for memory in manager.weighted_memories.values())
    # 旧客户端只带边界不带会话 ID：不套用到加权记忆，避免误伤别的会话
    legacy_scope = {"allowed_message_ids": {"x"}, "not_after_ts": 1.0}
    legacy = build_memory_visibility(branch_scope=legacy_scope, tree_reader=lambda _cid: EVENTS)
    assert legacy.branch_scope is None


def test_default_visibility_reads_request_context(monkeypatch):
    monkeypatch.setattr(read_gate, "_default_tree_reader", lambda _cid: EVENTS)
    manager = _manager()
    token = set_chat_history_branch_scope({"root", "a", "b"}, None, conversation_id=CONV)
    try:
        ranked = rerank_with_relation_graph(manager, _scored(manager, "m-b", "m-c"), limit=5)
    finally:
        reset_chat_history_branch_scope(token)
    assert "m-c" not in _ids(ranked)


def test_new_node_written_by_store_is_visible_without_rereading(monkeypatch):
    from core.services import chat_history_store
    from memory.topology.tree_registry import get_tree_registry

    events = list(EVENTS)
    reads = []

    def reader(cid):
        reads.append(cid)
        return list(events)

    monkeypatch.setattr(read_gate, "_default_tree_reader", reader)
    scope = {"allowed_message_ids": {"root", "a", "d"}, "not_after_ts": None, "conversation_id": CONV}
    late = _memory("m-d", ts=5.0, event="evt-d")
    first = build_memory_visibility(branch_scope=scope)
    assert first.is_visible(late)  # d 还没落盘：认不出节点 → compat 放行
    assert first.reasons["compat_pass:legacy_unknown"] == 1

    chat_history_store._sync_topology_tree([_event("d", "a", 5.0)])
    second = build_memory_visibility(branch_scope=scope)
    assert second.is_visible(late) and not second.reasons  # 增量挂上的 d 在 anchor 路径上
    assert not second.is_visible(_memory("m-b2", ts=3.0, event="evt-b"))
    assert reads == [CONV]  # 整个过程只全量读过一次
    assert get_tree_registry().full_loads == 1
