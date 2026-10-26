"""同一查询在不同原始读入口必须得到同一可见集（v3 E2）。

覆盖 conversation records、事件历史、提示词回填三条路径：被回滚的兄弟线
不能从其中一个入口漏回来。
"""

from __future__ import annotations

import asyncio

from core.agents.chat_agent_components.context_budget import history_fetch
from core.agents.chat_agent_components.message_branch import (
    reset_chat_history_branch_scope,
    set_chat_history_branch_scope,
)
from core.services import chat_history_store as chat_store_module
from memory.core import history_ops

CONV = "web_role_aveline"


def _event(node: str, parent: str = "", *, ts: float, role: str = "user") -> dict:
    payload = {
        "event_id": f"evt-{node}",
        "conversation_id": CONV,
        "role": role,
        "content": f"正文-{node}",
        "timestamp": ts,
        "event_type": "chat_message",
    }
    if node:
        payload["client_node_id"] = node
        payload["parent_node_id"] = parent
    return payload


def _events():
    return [
        _event("root", ts=1.0),
        _event("a", "root", ts=2.0, role="assistant"),
        _event("b", "a", ts=3.0),
        _event("c", "a", ts=4.0, role="assistant"),
        _event("", ts=0.5),
    ]


class _FakeStore:
    def __init__(self, events):
        self._events = events

    def list_conversation_events(
        self,
        conversation_id,
        *,
        limit=100,
        before=None,
        query=None,
        roles=None,
    ):
        items = [
            dict(item)
            for item in self._events
            if item.get("conversation_id") == conversation_id
        ]
        if roles:
            wanted = {str(role).lower() for role in roles}
            items = [item for item in items if str(item.get("role")).lower() in wanted]
        if before is not None:
            items = [item for item in items if float(item.get("timestamp") or 0) < before]
        if limit and limit > 0:
            return items[-int(limit) :]
        return items


def _activate_branch_scope():
    return set_chat_history_branch_scope({"root", "a", "b"}, None)


def test_conversation_records_hide_sibling_branch(monkeypatch):
    store = _FakeStore(_events())
    monkeypatch.setattr(history_ops, "get_chat_history_store", lambda: store)
    monkeypatch.setattr(chat_store_module, "get_chat_history_store", lambda: store)
    token = _activate_branch_scope()
    try:
        records = asyncio.run(
            history_ops.get_conversation_records(conversation_id=CONV, limit=10)
        )
    finally:
        reset_chat_history_branch_scope(token)

    joined = " ".join(record["content"] for record in records)
    assert "正文-c" not in joined
    assert "正文-b" in joined


def test_event_history_hide_sibling_branch(monkeypatch):
    store = _FakeStore(_events())
    monkeypatch.setattr(history_ops, "get_chat_history_store", lambda: store)
    monkeypatch.setattr(chat_store_module, "get_chat_history_store", lambda: store)
    token = _activate_branch_scope()
    try:
        items = asyncio.run(
            history_ops.get_event_history(object(), conversation_id=CONV, limit=20)
        )
    finally:
        reset_chat_history_branch_scope(token)

    event_ids = {item["event_id"] for item in items}
    assert "evt-c" not in event_ids
    assert {"evt-root", "evt-a", "evt-b"} <= event_ids


def test_prompt_backfill_hide_sibling_branch(monkeypatch):
    store = _FakeStore(_events())
    monkeypatch.setattr(history_ops, "get_chat_history_store", lambda: store)
    monkeypatch.setattr(chat_store_module, "get_chat_history_store", lambda: store)
    token = _activate_branch_scope()
    try:
        filled = asyncio.run(
            history_fetch._backfill_from_chat_history_store(
                [],
                object(),
                CONV,
                exclude_categories=[],
            )
        )
    finally:
        reset_chat_history_branch_scope(token)

    joined = " ".join(str(item.get("content") or "") for item in filled)
    assert "正文-c" not in joined
    assert "正文-b" in joined
