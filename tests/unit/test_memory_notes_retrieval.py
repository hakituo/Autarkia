"""派生笔记检索（v3 G）：混合检索、世界线闸门、向量旁挂缓存、工具接线。假向量，不加载模型。"""

from __future__ import annotations

import os
import time

import pytest

from core.tools import memory_notes_search
from memory.notes import NoteStore, embeddings, paths
from memory.notes.retrieval import NoteRetriever

SCOPE = "aveline"
CID = "web_role_aveline"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "notes_dir", lambda scope: tmp_path / "notes" / scope)
    return NoteStore(SCOPE)


def _write(store, segment_id, text, events, *, cid=CID, at=1000.0):
    store.replace_segment(
        cid,
        segment_id,
        "segment-episode-2",
        [{"kind": "episode", "text": text, "source_event_ids": tuple(events)}],
        segment_source_event_ids=events,
        occurred_from=at,
        occurred_to=at + 60,
    )


#: 假向量：含「城」的文本与「住」的问题同向，其余正交
def _embedder(calls=None):
    def embed(texts):
        if calls is not None:
            calls.append(list(texts))
        return [[1.0, 0.0] if ("城" in t or "住" in t) else [0.0, 1.0] for t in texts]

    return embed


def _no_gate(_payloads, _cid, _scope):
    return set()


def test_hybrid_finds_semantic_match_and_returns_time_and_sources(store):
    _write(store, "s1", "Master说他在山城长大，一直没离开过。", ["e1", "e2"], at=5000.0)
    _write(store, "s2", "Master今天吃了牛肉汤和葱油饼。", ["e3"])
    retriever = NoteRetriever(SCOPE, store=store, embedder=_embedder(), gate=_no_gate)

    hits = retriever.search("我住在哪个城市", conversation_id=CID, limit=1)
    assert [h["text"] for h in hits] == ["Master说他在山城长大，一直没离开过。"]
    assert hits[0]["occurred_from"] == 5000.0 and hits[0]["source_event_ids"] == ["e1", "e2"]
    # 关掉向量只剩 BM25：问句与原文不共享词，检不到（这正是需要混合检索的原因）
    assert retriever.search("我住在哪个城市", conversation_id=CID, use_vectors=False) == []


def test_note_hidden_when_any_source_event_is_on_sibling_branch(store):
    _write(store, "s1", "Master把茶换成了乌龙。", ["e1", "e2"])
    _write(store, "s2", "Master说早上喝乌龙茶。", ["e3"])

    def gate(payloads, cid, _scope):
        assert {p["event_id"] for p in payloads} == {"e1", "e2", "e3"} and cid == CID
        return {"e2"}  # 只有一条来源在兄弟线上，整条梗概也要隐藏

    retriever = NoteRetriever(SCOPE, store=store, embedder=_embedder(), gate=gate)
    hits = retriever.search("乌龙", conversation_id=CID, limit=5)
    assert [h["text"] for h in hits] == ["Master说早上喝乌龙茶。"]


def test_scope_wide_corpus_refreshes_after_new_write(store):
    retriever = NoteRetriever(SCOPE, store=store, embedder=_embedder(), gate=_no_gate)
    assert retriever.search("乌龙", conversation_id=CID) == []
    _write(store, "s1", "Master换成了乌龙茶。", ["e1"], cid="shared__persona__core_aveline")
    path = paths.notes_path(SCOPE, "shared__persona__core_aveline")
    os.utime(path, (time.time() + 5, time.time() + 5))  # 保证 mtime 变化
    hits = retriever.search("乌龙", conversation_id=CID)
    assert hits and hits[0]["conversation_id"] == "shared__persona__core_aveline"


def test_vector_sidecar_is_reused_capped_and_pruned(store):
    for index in range(3):
        _write(store, f"s{index}", f"笔记{index}", [f"e{index}"])
    notes = store.list_notes(CID)
    calls = []
    first = embeddings.load_vectors(SCOPE, CID, notes, _embedder(calls), max_new=2)
    assert len(first) == 2 and embeddings.vectors_path(SCOPE, CID).exists()
    second = embeddings.load_vectors(SCOPE, CID, notes, _embedder(calls), max_new=2)
    assert len(second) == 3 and [len(c) for c in calls] == [2, 1]
    # 笔记被替换后，旧向量从缓存里剔除
    third = embeddings.load_vectors(SCOPE, CID, notes[:1], _embedder(calls))
    assert set(third) == {notes[0]["note_id"]}


def test_merge_keeps_one_slot_for_old_results():
    notes = [{"content": f"n{i}"} for i in range(5)]
    others = [{"content": f"o{i}"} for i in range(5)]
    merged = memory_notes_search.merge_with_notes(notes, others, 5)
    assert [m["content"] for m in merged] == ["n0", "n1", "n2", "n3", "o0"]
    # 主动关怀等小 limit 也至少给梗概 limit-1 个位置
    assert [m["content"] for m in memory_notes_search.merge_with_notes(notes, others, 3)] == [
        "n0",
        "n1",
        "o0",
    ]
    assert memory_notes_search.merge_with_notes([], others, 3) == others[:3]
    assert memory_notes_search.merge_with_notes(notes, [], 3) == notes[:3]


def test_tool_entries_respect_switch_and_swallow_errors(store, monkeypatch):
    _write(store, "s1", "Master换成了乌龙茶。", ["e1"], at=7000.0)
    monkeypatch.setattr(
        "memory.notes.retrieval.read_gate_hidden", lambda payloads, cid, scope: set()
    )
    monkeypatch.setattr("memory.notes.embeddings.default_embedder", lambda: _embedder())
    entries = memory_notes_search.search_note_entries(CID, "乌龙", 5)
    assert entries[0]["source"] == "notes" and entries[0]["timestamp"] == 7000.0

    monkeypatch.setattr(memory_notes_search, "notes_retrieval_enabled", lambda: False)
    assert memory_notes_search.search_note_entries(CID, "乌龙", 5) == []

    monkeypatch.setattr(memory_notes_search, "notes_retrieval_enabled", lambda: True)
    monkeypatch.setattr("memory.notes.retrieval.NoteRetriever.search", _boom)
    assert memory_notes_search.search_note_entries(CID, "乌龙", 5) == []


def _boom(*_args, **_kwargs):
    raise RuntimeError("index broken")


def test_new_embedding_budget_is_shared_across_conversations(store, monkeypatch):
    monkeypatch.setattr(embeddings, "MAX_NEW_PER_CALL", 3)
    for cid in ("c1", "c2", "c3"):
        for index in range(2):
            _write(store, f"{cid}-s{index}", f"{cid}笔记{index}", [f"{cid}-e{index}"], cid=cid)
    calls = []
    NoteRetriever(SCOPE, store=store, embedder=_embedder(calls), gate=_no_gate).search(
        "笔记", conversation_id="c1"
    )
    # 3 个会话共 6 条缺向量，单次查询只现算 3 条（另 1 次是问句本身）
    assert sum(len(c) for c in calls[:-1]) == 3 and calls[-1] == ["笔记"]


def test_dense_failure_falls_back_to_bm25(store):
    _write(store, "s1", "Master换成了乌龙茶。", ["e1"])

    def broken(_texts):
        raise RuntimeError("model missing")

    hits = NoteRetriever(SCOPE, store=store, embedder=broken, gate=_no_gate).search(
        "乌龙茶", conversation_id=CID
    )
    assert [h["text"] for h in hits] == ["Master换成了乌龙茶。"]


def test_sfw_request_excludes_sensitive_notes_like_legacy_memories(store, monkeypatch):
    _write(store, "s1", "Master换成了乌龙茶。", ["e1"])
    _write(store, "s2", "Master让我说骚话，玩了色色的扮演，乌龙茶也提了一句。", ["e2"])
    monkeypatch.setattr("memory.notes.retrieval.read_gate_hidden", lambda p, c, s: set())
    monkeypatch.setattr("memory.notes.embeddings.default_embedder", lambda: _embedder())
    monkeypatch.setattr("core.utils.privacy.get_privacy_isolation_enabled", lambda: True)

    sfw = memory_notes_search.search_note_entries(CID, "乌龙茶", 5, request_scope="sfw")
    assert [e["content"] for e in sfw] == ["Master换成了乌龙茶。"]
    private = memory_notes_search.search_note_entries(CID, "乌龙茶", 5, request_scope="private")
    assert len(private) == 2
