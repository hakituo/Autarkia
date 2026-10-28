"""expand_memory：按梗概编号展开原话（闸门 / scope / 截断 / SFW / 注册 / 编号显示）。不调模型。"""

from __future__ import annotations

import asyncio

import pytest

from core.tools import expand_memory_tool as em
from core.tools import memory_notes_search
from memory.notes import NoteStore, paths

SCOPE = "aveline"
CID = "web_role_aveline"
OTHER_SCOPE_CID = "web_role_ling"


class FakeHistory:
    def __init__(self, events):
        self.events = events
        self.calls = []

    def list_conversation_events(self, conversation_id, *, limit=100, **_kwargs):
        self.calls.append((conversation_id, limit))
        return [e for e in self.events if e["conversation_id"] == conversation_id]


def _event(event_id, role, content, ts, cid=CID):
    return {
        "event_id": event_id,
        "conversation_id": cid,
        "role": role,
        "content": content,
        "timestamp": ts,
        "storage_scope": SCOPE,
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    """梗概库落临时目录；会话 → scope 用固定映射；默认闸门全放行、非 SFW。"""
    from core.agents.chat_agent_components import message_branch
    from core.utils import privacy
    from core.utils.data import data_paths
    from memory.topology import read_gate

    monkeypatch.setattr(paths, "notes_dir", lambda scope: tmp_path / "notes" / scope)
    scopes = {CID: "aveline", OTHER_SCOPE_CID: "ling"}
    monkeypatch.setattr(
        data_paths,
        "resolve_data_scope_from_conversation_id",
        lambda cid, default="aveline": scopes.get(cid, default),
    )
    monkeypatch.setattr(
        message_branch, "filter_events_by_branch_scope", lambda items, **_kw: list(items)
    )
    monkeypatch.setattr(
        read_gate,
        "filter_raw_events",
        lambda items, **_kw: read_gate.GateOutcome(events=list(items)),
    )
    monkeypatch.setattr(privacy, "should_exclude_sensitive", lambda **_kw: False)
    store = NoteStore(SCOPE)
    store.replace_segment(
        CID,
        "s1",
        "segment-episode-2",
        [{"kind": "episode", "text": "聊到周末去海边。", "source_event_ids": ("e2", "e1")}],
        segment_source_event_ids=["e1", "e2"],
        occurred_from=1000.0,
        occurred_to=1100.0,
    )
    note = store.list_notes(CID)[0]
    history = FakeHistory(
        [
            _event("e1", "user", "周末想去海边", 1000.0),
            _event("e2", "assistant", "好呀，带上防晒", 1010.0),
            _event("e9", "user", "无关的一句", 1200.0),
        ]
    )
    return {"note": note, "history": history, "monkeypatch": monkeypatch}


def _expand(env, ref=None, **kwargs):
    ref = ref if ref is not None else em.short_note_ref(env["note"]["note_id"])
    return em.expand_note(CID, ref, history_store=env["history"], **kwargs)


def test_expand_returns_source_events_in_time_order(env):
    out = _expand(env)
    assert out.splitlines()[1:] == ["用户：周末想去海边", "我：好呀，带上防晒"]
    assert "无关的一句" not in out
    # 完整编号、带 # 前缀同样能找到；取原文时不截断条数
    assert _expand(env, "#" + env["note"]["note_id"]) == out
    assert env["history"].calls[-1] == (CID, 0)


def test_any_hidden_source_event_blocks_whole_expansion(env):
    from memory.topology import read_gate

    env["monkeypatch"].setattr(
        read_gate,
        "filter_raw_events",
        lambda items, **_kw: read_gate.GateOutcome(
            events=[e for e in items if e["event_id"] != "e2"]
        ),
    )
    assert _expand(env) == em.MSG_UNAVAILABLE


def test_branch_scope_hidden_and_gate_error_block_expansion(env):
    from core.agents.chat_agent_components import message_branch
    from memory.topology import read_gate

    mp = env["monkeypatch"]
    mp.setattr(
        message_branch,
        "filter_events_by_branch_scope",
        lambda items, **_kw: [e for e in items if e["event_id"] != "e1"],
    )
    assert _expand(env) == em.MSG_UNAVAILABLE

    mp.setattr(message_branch, "filter_events_by_branch_scope", lambda items, **_kw: list(items))

    def boom(*_a, **_kw):
        raise RuntimeError("tree broken")

    mp.setattr(read_gate, "filter_raw_events", boom)
    assert _expand(env) == em.MSG_FAILED  # 闸门出错不退回放行


def test_missing_source_event_blocks_expansion(env):
    env["history"].events = [e for e in env["history"].events if e["event_id"] != "e2"]
    assert _expand(env) == em.MSG_UNAVAILABLE


def test_note_in_other_scope_is_not_found(env):
    ref = em.short_note_ref(env["note"]["note_id"])
    assert em.expand_note(OTHER_SCOPE_CID, ref, history_store=env["history"]) == em.MSG_NOT_FOUND
    assert _expand(env, "note_ffffffff") == em.MSG_NOT_FOUND
    assert _expand(env, "") == em.MSG_NO_REF


def test_long_text_is_truncated_and_marked(env):
    env["history"].events[0]["content"] = "海" * 300
    out = _expand(env, max_chars=200)
    body = out.split("\n", 1)[1]
    assert "已截断" in body and "另有 1 条未显示" in body
    assert "好呀" not in body
    assert len(body.splitlines()[0]) <= 200 + len("用户：") + 2


def test_sfw_excludes_sensitive_note_or_source(env):
    from core.utils import privacy

    mp = env["monkeypatch"]
    mp.setattr(privacy, "should_exclude_sensitive", lambda scope=None, **_kw: scope == "sfw")
    mp.setattr(memory_notes_search, "is_sensitive_note", lambda text: "防晒" in str(text))
    assert _expand(env, request_scope="sfw") == em.MSG_UNAVAILABLE
    assert "防晒" in _expand(env, request_scope="private")

    mp.setattr(memory_notes_search, "is_sensitive_note", lambda text: "海边" in str(text))
    assert _expand(env, request_scope="sfw") == em.MSG_UNAVAILABLE


def test_tool_registered_with_schema():
    from core.tools.registry import ToolRegistry, register_all_tools

    registry = ToolRegistry()
    register_all_tools(registry)
    tool = registry.get_tool("expand_memory")
    assert isinstance(tool, em.ExpandMemoryTool)
    assert "search_memory" in tool.description and "原话" in tool.description
    fields = em.ExpandMemoryInput.model_fields
    assert set(fields) == {"note_id", "max_chars"} and fields["max_chars"].default == 1500


def test_tool_without_user_id_returns_message():
    tool = em.ExpandMemoryTool()
    tool.set_runtime_context({})
    assert "user_id" in asyncio.run(tool._run(note_id="note_1234abcd"))


def test_search_memory_note_line_carries_short_ref(monkeypatch):
    from core.tools import search_memory_tool

    entry = {
        "content": "聊到周末去海边。",
        "timestamp": 0,
        "source": memory_notes_search.SOURCE_NOTES,
        "category": "episode",
        "note_id": "note_0123456789abcdef01234567",
        "source_event_ids": ["e1"],
    }
    monkeypatch.setattr(search_memory_tool, "search_note_entries", lambda *a, **k: [entry])
    tool = search_memory_tool.SearchMemoryTool()
    tool.set_runtime_context({"agent": None, "user_id": CID, "scope": "private"})
    out = asyncio.run(tool._run(query="海边", include_chat_history=False))
    assert "- [梗概] 聊到周末去海边。 #note_01234567" in out
