"""原始聊天事件的 v3 字段、幂等去重与内容门控（D1-D4 写入侧）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.agents.chat_agent_components.message_branch import (
    reset_request_branch_metadata,
    set_request_branch_metadata,
)
from core.services.chat_history_idempotency import IdempotencyGuard
from core.services.chat_history_store import ChatHistoryStore

_NOW = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
_CONV = "shared__persona__core_aveline"


@pytest.fixture()
def store(tmp_path: Path) -> ChatHistoryStore:
    return ChatHistoryStore(base_dir=tmp_path)


def _lines(base_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(base_dir.rglob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _append(
    store: ChatHistoryStore,
    *,
    role: str,
    content: str,
    message_id: str,
    platform: str = "",
):
    return store.append_event(
        conversation_id=_CONV,
        role=role,
        content=content,
        message_id=message_id,
        event_type="chat_message" if role == "user" else "chat_reply",
        metadata={"platform": platform} if platform else None,
        now_dt=_NOW,
    )


def test_branch_metadata_moves_to_raw_event(store, tmp_path):
    token = set_request_branch_metadata(
        {
            "user_message_id": "u1",
            "user_parent_id": "p0",
            "assistant_message_id": "a1",
            "assistant_parent_id": "u1",
        }
    )
    try:
        _append(store, role="user", content="你好", message_id="a1")
        _append(store, role="assistant", content="在的", message_id="a1")
    finally:
        reset_request_branch_metadata(token)

    rows = _lines(tmp_path)
    user_row = next(row for row in rows if row["role"] == "user")
    assistant_row = next(row for row in rows if row["role"] == "assistant")

    assert user_row["client_node_id"] == "u1"
    assert user_row["parent_node_id"] == "p0"
    assert assistant_row["client_node_id"] == "a1"
    assert assistant_row["parent_node_id"] == "u1"
    assert user_row["turn_id"] == "a1"
    assert assistant_row["turn_id"] == "a1"
    assert user_row["topology_status"] == "complete"
    assert user_row["namespace"] == "aveline"
    assert user_row["continuity_id"].startswith("continuity:")
    assert user_row["idempotency_key"]


def test_event_without_branch_metadata_is_marked_unknown(store, tmp_path):
    _append(store, role="user", content="没有客户端节点", message_id="turn-1")

    row = _lines(tmp_path)[0]

    assert row["client_node_id"] == ""
    assert row["topology_status"] == "unknown"
    assert row["idempotency_key"]


def test_reposting_same_client_node_is_deduplicated(store, tmp_path):
    token = set_request_branch_metadata(
        {
            "user_message_id": "u9",
            "assistant_message_id": "a9",
            "assistant_parent_id": "u9",
        }
    )
    try:
        first = _append(store, role="user", content="重投测试", message_id="a9")
        second = _append(store, role="user", content="重投测试", message_id="a9")
    finally:
        reset_request_branch_metadata(token)

    rows = _lines(tmp_path)

    assert len(rows) == 1
    assert first["event_id"] == second["event_id"]
    assert second["deduplicated"] is True


def test_reposting_without_client_node_uses_content_and_second(store, tmp_path):
    first = _append(store, role="user", content="同一条重投", message_id="turn-x")
    second = _append(store, role="user", content="同一条重投", message_id="turn-x")

    assert len(_lines(tmp_path)) == 1
    assert first["event_id"] == second["event_id"]


def test_media_placeholder_keeps_topology_but_not_eligible(store, tmp_path):
    _append(store, role="user", content="[图片]", message_id="turn-img")

    row = _lines(tmp_path)[0]

    assert row["content_eligible"] is False
    assert row["content"] == "[图片]"
    assert row["event_id"]


def test_debug_message_is_still_filtered(store, tmp_path):
    _append(store, role="assistant", content="[DEBUG_ERROR] 内部错误", message_id="turn-err")

    assert _lines(tmp_path) == []


def test_linear_platform_attaches_each_message_to_previous_head(store, tmp_path):
    _append(store, role="user", content="QQ 第一条", message_id="q1", platform="qq")
    _append(store, role="assistant", content="QQ 第二条", message_id="q2", platform="qq")

    rows = _lines(tmp_path)

    assert rows[0]["client_node_id"].startswith("srv:")
    assert rows[0]["parent_node_id"] == ""
    assert rows[0]["topology_status"] == "partial"
    assert rows[1]["parent_node_id"] == rows[0]["client_node_id"]
    assert rows[1]["topology_status"] == "complete"


def test_linear_head_survives_new_store_instance(tmp_path):
    ChatHistoryStore(base_dir=tmp_path).append_event(
        conversation_id=_CONV,
        role="user",
        content="重启前",
        message_id="q1",
        metadata={"platform": "qq"},
        now_dt=_NOW,
    )
    from memory.topology.linear import get_linear_head_tracker

    get_linear_head_tracker().clear()
    ChatHistoryStore(base_dir=tmp_path).append_event(
        conversation_id=_CONV,
        role="user",
        content="重启后",
        message_id="q2",
        metadata={"platform": "qq"},
        now_dt=_NOW,
    )

    rows = _lines(tmp_path)
    assert rows[1]["parent_node_id"] == rows[0]["client_node_id"]


def test_guard_forgets_deleted_file(tmp_path):
    guard = IdempotencyGuard()
    path = tmp_path / "a.jsonl"
    accepted, duplicates = guard.reserve(
        path, [{"event_id": "e1", "idempotency_key": "k1"}]
    )
    assert len(accepted) == 1 and duplicates == {}

    guard.forget(path)
    accepted, duplicates = guard.reserve(
        path, [{"event_id": "e2", "idempotency_key": "k1"}]
    )
    assert len(accepted) == 1 and duplicates == {}


def test_store_write_feeds_resident_tree(store, monkeypatch):
    from memory.topology import tree_registry

    registry = tree_registry.TreeRegistry(reader=lambda _cid: [])
    monkeypatch.setattr(tree_registry, "get_tree_registry", lambda: registry)
    registry.tree(_CONV)  # 先加载（空树），之后的写入走增量

    token = set_request_branch_metadata(
        {"user_message_id": "u5", "assistant_message_id": "a5", "assistant_parent_id": "u5"}
    )
    try:
        _append(store, role="user", content="带节点的新消息", message_id="a5")
        _append(store, role="assistant", content="回复", message_id="a5")
    finally:
        reset_request_branch_metadata(token)
    tree = registry.tree(_CONV)
    assert set(tree.nodes) == {"u5", "a5"}
    assert tree.nodes["a5"].parent_id == "u5"
    assert registry.full_loads == 1


def test_thought_event_shares_assistant_node(store, tmp_path):
    token = set_request_branch_metadata(
        {"user_message_id": "u8", "assistant_message_id": "a8", "assistant_parent_id": "u8"}
    )
    try:
        store.append_event(
            conversation_id=_CONV, role="system", content="想了想", message_id="a8",
            event_type="chat_thought", now_dt=_NOW,
        )
    finally:
        reset_request_branch_metadata(token)
    row = _lines(tmp_path)[0]
    assert row["client_node_id"] == "a8"
    assert row["parent_node_id"] == "u8"
