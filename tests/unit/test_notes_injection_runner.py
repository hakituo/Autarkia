"""梗概自动注入的取数与接入：读闸门隐藏、SFW 过滤、缓存、开关关时 prompt 逐字节不变。

笔记库目录由 conftest 的 ``_reset_note_retrieval_cache`` 指到临时目录；向量用假 embedder，
不加载 bge。敏感判定用标记字符串替身，测试里不出现任何敏感词。
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time

import pytest

from core.agents.chat_agent_components import context as ctx
from core.agents.chat_agent_components.context_budget import memory_injection
from memory.notes import injection
from memory.notes.injection import runner
from memory.notes.retrieval import NoteRetriever
from memory.notes.store import NoteStore

SCOPE = "aveline"
CID = "conv_a"
NOW = time.time()


def _fake_embedder(texts):
    out = []
    for text in texts:
        digest = hashlib.sha256(str(text).encode("utf-8")).digest()
        out.append([b / 255.0 + 0.01 for b in digest[:16]])
    return out


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch):
    runner.reset_injection_cache()
    monkeypatch.setattr(
        "core.tools.memory_notes_search.is_sensitive_note", lambda text: "[S]" in str(text)
    )
    yield
    runner.reset_injection_cache()


def _seed(store: NoteStore) -> None:
    drafts = [
        {"kind": "episode", "text": "聊了期中考试的复习计划和数学错题", "source_event_ids": ["e1"]},
        {"kind": "episode", "text": "[S] 期中考试之后的私密话题", "source_event_ids": ["e2"]},
        {"kind": "plan", "text": "周六上午去图书馆复习", "source_event_ids": ["e3"]},
        {"kind": "plan", "text": "在另一条世界线上约好的计划", "source_event_ids": ["e4"]},
        {
            "kind": "preference",
            "text": "不喜欢香菜",
            "importance": 0.8,
            "source_event_ids": ["e5"],
        },
        {"kind": "preference", "text": "随口提到的偏好", "importance": 0.5, "source_event_ids": ["e6"]},
    ]
    store.replace_segment(
        CID,
        "seg1",
        "test_v1",
        drafts,
        segment_source_event_ids=[f"e{i}" for i in range(1, 7)],
        occurred_from=NOW - 3600,
        occurred_to=NOW - 3000,
    )


def _gate_hiding(*hidden_ids):
    calls = []

    def gate(payloads, conversation_id, branch_scope):
        calls.append([p["event_id"] for p in payloads])
        return {p["event_id"] for p in payloads} & set(hidden_ids)

    gate.calls = calls
    return gate


def _build(exclude_sensitive, gate, query="期中考试复习", existing=()):
    store = NoteStore(SCOPE)
    retriever = NoteRetriever(SCOPE, store=store, embedder=_fake_embedder, gate=gate)
    return runner.build_block(
        user_id=CID,
        query=query,
        exclude_sensitive=exclude_sensitive,
        existing=existing,
        store=store,
        retriever=retriever,
        gate=gate,
    )


def test_block_contains_relevant_plan_and_preferences_in_importance_order():
    _seed(NoteStore(SCOPE))
    block = _build(False, _gate_hiding())
    assert block.startswith(injection.selection.HEADER)
    assert "期中考试的复习计划" in block
    assert "周六上午去图书馆复习" in block
    assert block.index("不喜欢香菜") < block.index("随口提到的偏好")


def test_done_plan_hidden_by_gate_does_not_close_plan_on_this_line():
    store = NoteStore(SCOPE)
    _seed(store)
    store.replace_segment(
        CID, "seg2", "test_v1",
        [{"kind": "plan", "text": "周六上午去图书馆复习", "source_event_ids": ["e9"],
          "metadata": {"status": "done"}}],
        segment_source_event_ids=["e9"], occurred_from=NOW - 600, occurred_to=NOW - 300,
    )
    assert "图书馆" not in _build(False, _gate_hiding(), query="")
    runner.reset_injection_cache()
    # 收尾条目在兄弟线上：计划在本线仍未完成
    assert "图书馆" in _build(False, _gate_hiding("e9"), query="")


def test_gate_hides_notes_on_other_worldline_for_every_section():
    _seed(NoteStore(SCOPE))
    block = _build(False, _gate_hiding("e4", "e1"))
    assert "另一条世界线" not in block  # 计划类走闸门
    assert "期中考试的复习计划" not in block  # 相关类走 retriever 内置闸门
    assert "周六上午去图书馆复习" in block


def test_sfw_filter_removes_sensitive_notes_only_when_excluding():
    _seed(NoteStore(SCOPE))
    assert "[S]" not in _build(True, _gate_hiding(), query="期中考试 私密话题")
    runner.reset_injection_cache()
    assert "[S]" in _build(False, _gate_hiding(), query="期中考试 私密话题")


def test_dedupe_against_existing_injection():
    _seed(NoteStore(SCOPE))
    block = _build(False, _gate_hiding(), existing=["[10-20] 记得她说过不喜欢香菜"])
    assert "不喜欢香菜" not in block


def test_empty_store_returns_empty_and_skips_gate():
    gate = _gate_hiding()
    assert _build(False, gate) == ""
    assert gate.calls == []


def test_same_turn_rejudges_gate_after_branch_switch():
    """结果不缓存：同一句话、梗概没变，切分支后闸门变了，立刻按新分支判。"""
    _seed(NoteStore(SCOPE))
    assert "周六上午去图书馆复习" in _build(False, _gate_hiding())
    assert "周六上午去图书馆复习" not in _build(False, _gate_hiding("e3"))


def test_private_local_only_switch_controls_cloud_path(monkeypatch):
    monkeypatch.setattr("core.utils.privacy.get_privacy_isolation_enabled", lambda: False)
    monkeypatch.setattr(injection, "private_local_only", lambda: True)
    assert injection.exclude_sensitive_for(is_cloud=True, is_sensitive_mode=True) is True
    assert injection.exclude_sensitive_for(is_cloud=False, is_sensitive_mode=False) is False
    # 关掉「只进本地」：云端也按全局隐私隔离判断
    monkeypatch.setattr(injection, "private_local_only", lambda: False)
    assert injection.exclude_sensitive_for(is_cloud=True, is_sensitive_mode=False) is False
    monkeypatch.setattr("core.utils.privacy.get_privacy_isolation_enabled", lambda: True)
    assert injection.exclude_sensitive_for(is_cloud=True, is_sensitive_mode=False) is True


def test_settings_default_off(monkeypatch):
    monkeypatch.delenv("XIAOYOU_MEMORY_NOTES_INJECTION_ENABLED", raising=False)
    monkeypatch.delenv("XIAOYOU_MEMORY_NOTES_INJECTION_PRIVATE_LOCAL_ONLY", raising=False)
    from config.settings_core import MemorySettings

    assert MemorySettings().notes_injection_enabled is False
    assert MemorySettings().notes_injection_private_local_only is True


def test_timeout_returns_empty(monkeypatch):
    release = threading.Event()

    def _blocked(**kwargs):
        release.wait(5)  # 由协程在超时返回后放行，不靠 sleep 卡时间
        return "late"

    monkeypatch.setattr(injection, "build_block", _blocked)

    async def _main():
        try:
            return await injection.build_notes_injection(
                user_id=CID, message_text="hi", is_cloud=True, is_sensitive_mode=False,
                timeout=0.01,
            )
        finally:
            release.set()

    assert asyncio.run(_main()) == ""


def test_call_point_off_leaves_injections_untouched(monkeypatch):
    monkeypatch.setattr(injection, "injection_enabled", lambda: False)

    def _boom(**kwargs):
        raise AssertionError("开关关闭时不得取数")

    monkeypatch.setattr(injection, "build_block", _boom)
    items = ["thinking", "sensitive"]
    asyncio.run(
        memory_injection.inject_note_memories(
            user_id=CID, message_text="hi", is_cloud=False, is_sensitive_mode=False,
            injections=items,
        )
    )
    assert items == ["thinking", "sensitive"]


def _patch_context(monkeypatch, captured):
    async def _tools(agent, message_text, model_hint, **kwargs):
        return []

    async def _persona(**kwargs):
        return "PERSONA"

    async def _scope(**kwargs):
        return ("cloud", False)

    async def _history(memory_manager, user_id, scope, **kwargs):
        return [{"role": "user", "content": "历史"}]

    def _complete(**kwargs):
        captured.append(kwargs)
        return [{"role": "user", "content": repr(sorted(kwargs.get("sensitive_injections")))}]

    monkeypatch.setattr(ctx, "_prepare_active_tools", _tools)
    monkeypatch.setattr(ctx, "_resolve_persona_prompt", _persona)
    monkeypatch.setattr(ctx, "_resolve_scope_and_sensitive_mode", _scope)
    monkeypatch.setattr(ctx, "_fetch_history_for_scope", _history)
    monkeypatch.setattr(ctx, "filter_tool_names", lambda names, **kwargs: list(names))
    monkeypatch.setattr(ctx, "_detect_cloud_mode", lambda agent, hint: True)
    monkeypatch.setattr(ctx, "is_debug_enabled", lambda key: False)
    monkeypatch.setattr(
        "core.agents.chat_agent_components.persona_system.prompt.build_complete_message_list",
        _complete,
    )


class _Agent:
    tool_registry = None
    _mm = object()

    def _get_memory_manager(self, user_id):
        return self._mm


def test_prompt_byte_identical_when_switch_off(monkeypatch):
    """开关关：与「没有这个调用点」时传给 prompt 组装的入参完全相同，且有数据也不注入。"""
    _seed(NoteStore(SCOPE))
    monkeypatch.setattr(injection, "injection_enabled", lambda: False)
    captured: list = []
    _patch_context(monkeypatch, captured)
    agent = _Agent()
    with_call = asyncio.run(ctx.build_conversation_history(agent, CID, "期中考试复习"))

    async def _absent(**kwargs):
        return None

    monkeypatch.setattr(ctx, "_inject_note_memories", _absent)
    without_call = asyncio.run(ctx.build_conversation_history(agent, CID, "期中考试复习"))
    assert with_call == without_call
    assert captured[0] == captured[1]
    assert captured[0]["sensitive_injections"] == []


def test_switch_on_appends_block_on_cloud_path(monkeypatch):
    _seed(NoteStore(SCOPE))
    monkeypatch.setattr(injection, "injection_enabled", lambda: True)
    monkeypatch.setattr(
        "core.utils.data.data_paths.resolve_data_scope_from_conversation_id", lambda cid: SCOPE
    )
    monkeypatch.setattr("memory.notes.retrieval.read_gate_hidden", _gate_hiding())
    monkeypatch.setattr("memory.notes.embeddings.default_embedder", lambda: _fake_embedder)
    captured: list = []
    _patch_context(monkeypatch, captured)
    asyncio.run(ctx.build_conversation_history(_Agent(), CID, "期中考试 私密话题"))
    injections = captured[0]["sensitive_injections"]
    assert len(injections) == 1 and injections[0].startswith(injection.selection.HEADER)
    assert "[S]" not in injections[0]  # 云端默认不带隐私梗概
