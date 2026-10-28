"""梗概检索的重要度微调：只在相关度相近时改变先后，0.5 档与改动前逐条一致。假向量，不加载模型。"""

from __future__ import annotations

import math

import pytest

from memory.notes import NoteStore, paths, retrieval
from memory.notes.retrieval import (
    CANDIDATES_PER_ROUTE,
    IMPORTANCE_WEIGHT,
    RRF_K,
    NoteRetriever,
    importance_adjustment,
)

SCOPE = "aveline"
CID = "web_role_aveline"
#: 与梗概不共享任何词，BM25 一路为空，排序完全由假向量决定
QUERY = "zzqqxx"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "notes_dir", lambda scope: tmp_path / "notes" / scope)
    return NoteStore(SCOPE)


def _write(store, index, text, importance=None):
    note = {"kind": "episode", "text": text, "source_event_ids": (f"e{index}",)}
    if importance is not None:
        note["importance"] = importance
    store.replace_segment(
        CID,
        f"s{index}",
        "segment-episode-8",
        [note],
        segment_source_event_ids=[f"e{index}"],
        occurred_from=1000.0 + index,
        occurred_to=1060.0 + index,
    )


def _ranked_embedder(order):
    """order 里越靠前的文本与问题夹角越小，即向量一路名次就是 order 的下标。"""

    def embed(texts):
        out = []
        for text in texts:
            angle = 0.0 if text == QUERY else 0.01 * (order.index(text) + 1)
            out.append([math.cos(angle), math.sin(angle)])
        return out

    return embed


def _search(store, order, limit=10):
    retriever = NoteRetriever(
        SCOPE, store=store, embedder=_ranked_embedder(order), gate=lambda *_: set()
    )
    return retriever.search(QUERY, conversation_id=CID, limit=limit)


def test_close_relevance_prefers_higher_importance(store):
    order = ["梗概甲", "梗概乙"]
    _write(store, 0, "梗概甲", 0.5)
    _write(store, 1, "梗概乙", 0.8)
    hits = _search(store, order)
    # 相邻名次 RRF 只差 1/61-1/62，0.8 档的 +0.0003 足以翻转
    assert [h["text"] for h in hits] == ["梗概乙", "梗概甲"]
    top = hits[0]
    assert top["rrf_score"] == round(1 / (RRF_K + 2), 6)
    assert top["importance_adjust"] == round(IMPORTANCE_WEIGHT * 0.3, 6)
    assert top["score"] == round(top["rrf_score"] + top["importance_adjust"], 6)
    assert hits[1]["importance_adjust"] == 0.0


def test_large_relevance_gap_is_not_flipped(store):
    order = [f"梗概{i}" for i in range(12)]
    for i, text in enumerate(order):
        _write(store, i, text, 0.3 if i == 0 else 0.5)
    _write(store, 99, "梗概末", 0.8)
    order.append("梗概末")
    hits = _search(store, order, limit=13)
    texts = [h["text"] for h in hits]
    # 榜首即使是 0.3 档也守住第一；第 13 名的 0.8 档最多上移一两位，进不了前十
    assert texts[0] == "梗概0"
    assert texts.index("梗概末") >= 10


def test_full_scale_adjustment_cannot_beat_two_route_consensus():
    worst_two_routes = 2 / (RRF_K + CANDIDATES_PER_ROUTE) + importance_adjustment(
        {"importance": 0.0}
    )
    best_one_route = 1 / (RRF_K + 1) + importance_adjustment({"importance": 1.0})
    assert worst_two_routes > best_one_route


def test_all_neutral_importance_keeps_previous_order(store, monkeypatch):
    texts = [f"山城笔记{i % 4} 第{i}条" for i in range(20)]
    order = sorted(texts, key=lambda t: (int(t.split("第")[1][:-1]) * 7) % 20)
    for i, text in enumerate(texts):
        # 一半显式 0.5、一半缺省（store 兜底 0.5），都应调整为 0
        _write(store, i, text, 0.5 if i % 2 else None)
    retriever = NoteRetriever(
        SCOPE, store=store, embedder=_ranked_embedder(order + [QUERY]), gate=lambda *_: set()
    )
    queries = [QUERY, "山城笔记2", "山城笔记1 第3条"]
    after = [retriever.search(q, conversation_id=CID, limit=20) for q in queries]
    monkeypatch.setattr(retrieval, "importance_adjustment", lambda _note: 0.0)
    before = [retriever.search(q, conversation_id=CID, limit=20) for q in queries]
    assert after == before
    for hits in after:
        assert hits and all(h["score"] == h["rrf_score"] for h in hits)
        assert all(h["importance_adjust"] == 0.0 for h in hits)


@pytest.mark.parametrize("value", [None, "abc", float("nan"), 0.5])
def test_missing_or_bad_importance_is_neutral(value):
    assert importance_adjustment({"importance": value}) == 0.0
    assert importance_adjustment({}) == 0.0


def test_importance_is_clamped_to_unit_range():
    assert importance_adjustment({"importance": 5}) == pytest.approx(IMPORTANCE_WEIGHT * 0.5)
    assert importance_adjustment({"importance": -3}) == pytest.approx(-IMPORTANCE_WEIGHT * 0.5)
