"""派生笔记检索（v3 G）：BM25 + 向量 RRF 融合 → 世界线闸门 → 带时间与来源的结果。

C8 结论：每段梗概作主检索单元、混合检索最好；原文不与梗概同池排序，需要原话时按
``source_event_ids`` 回原始事件取（展开同样走闸门）。

可见性（spec §9 第 2 条）：梗概只在它的**全部**来源事件都通过读闸门时可见——任何一条
落在兄弟线上就整条隐藏；compat 模式下无拓扑的历史照常放行（与原始事件读口径一致）。
范围是整个记忆 scope（与旧加权记忆口径一致），各会话按自己的树 / 游标判定。
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from core.utils.logger import get_logger

from . import embeddings
from .bm25 import BM25
from .store import NoteStore

logger = get_logger("NoteRetrieval")

#: RRF 常数与每路候选数（与 C8 实验的 hybrid 检索一致）
RRF_K = 60
CANDIDATES_PER_ROUTE = 50

#: 闸门函数：(事件 payload 列表, 请求会话, 分支边界) -> 被隐藏的 event_id 集合
Gate = Callable[[list[dict[str, Any]], str, Mapping[str, Any] | None], set[str]]


@dataclass
class _Corpus:
    stamps: dict[str, float] = field(default_factory=dict)
    notes: list[dict[str, Any]] = field(default_factory=list)
    bm25: BM25 | None = None


_cache: dict[str, _Corpus] = {}
_cache_lock = threading.Lock()


def reset_note_retrieval_cache() -> None:
    with _cache_lock:
        _cache.clear()


def read_gate_hidden(
    payloads: list[dict[str, Any]], conversation_id: str, branch_scope: Mapping[str, Any] | None
) -> set[str]:
    """生产闸门：与 search_chat_history 同一套 ``read_gate``（compat，默认读请求上下文）。"""
    from memory.topology.read_gate import filter_raw_events

    outcome = filter_raw_events(
        payloads, conversation_id=conversation_id, branch_scope=branch_scope
    )
    visible = {str(item.get("event_id")) for item in outcome.events}
    return {str(item["event_id"]) for item in payloads} - visible


def _file_stamp(store: NoteStore, conversation_id: str) -> float:
    from .paths import notes_path

    try:
        return os.path.getmtime(notes_path(store.scope, conversation_id))
    except OSError:
        return 0.0


def _load_corpus(store: NoteStore) -> _Corpus:
    conversations = store.list_conversations()
    stamps = {cid: _file_stamp(store, cid) for cid in conversations}
    with _cache_lock:
        cached = _cache.get(store.scope)
        if cached and cached.stamps == stamps:
            return cached
    notes = [note for cid in conversations for note in store.list_notes(cid)]
    notes = [note for note in notes if str(note.get("text") or "").strip()]
    corpus = _Corpus(stamps=stamps, notes=notes, bm25=BM25([n["text"] for n in notes]))
    with _cache_lock:
        _cache[store.scope] = corpus
    return corpus


class NoteRetriever:
    def __init__(
        self,
        scope: str,
        *,
        store: NoteStore | None = None,
        embedder: embeddings.Embedder | None = None,
        gate: Gate | None = None,
    ) -> None:
        self.store = store or NoteStore(scope)
        self._embedder = embedder
        self._gate = gate or read_gate_hidden

    def _embedder_or_default(self) -> embeddings.Embedder:
        if self._embedder is None:
            self._embedder = embeddings.default_embedder()
        return self._embedder

    def _dense_ranking(self, corpus: _Corpus, query: str) -> list[int]:
        embedder = self._embedder_or_default()
        vectors: dict[str, np.ndarray] = {}
        by_conversation: dict[str, list[dict[str, Any]]] = {}
        for note in corpus.notes:
            by_conversation.setdefault(str(note.get("conversation_id") or ""), []).append(note)
        # 现算向量的上限按「一次查询」算，多个会话共用同一份预算
        budget = embeddings.MAX_NEW_PER_CALL
        for cid, notes in by_conversation.items():
            found, computed = embeddings.load_vectors_counted(
                self.store.scope, cid, notes, embedder, max_new=budget
            )
            vectors.update(found)
            budget = max(budget - computed, 0)
        query_vec = np.asarray(embedder([query])[0], dtype=np.float32)
        query_vec /= np.linalg.norm(query_vec) or 1.0
        scored = [
            (float(vectors[note["note_id"]] @ query_vec), index)
            for index, note in enumerate(corpus.notes)
            if note["note_id"] in vectors
        ]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [index for _score, index in scored[:CANDIDATES_PER_ROUTE]]

    def search(
        self,
        query: str,
        *,
        conversation_id: str,
        limit: int = 5,
        branch_scope: Mapping[str, Any] | None = None,
        use_vectors: bool = True,
    ) -> list[dict[str, Any]]:
        corpus = _load_corpus(self.store)
        if not corpus.notes or not str(query or "").strip():
            return []
        rankings = [corpus.bm25.rank(query, CANDIDATES_PER_ROUTE)] if corpus.bm25 else []
        if use_vectors:
            try:
                rankings.append(self._dense_ranking(corpus, query))
            except Exception as exc:  # noqa: BLE001 - 向量模型 / 缓存出错时退回纯 BM25
                logger.warning("梗概向量检索失败，退回 BM25: %s", type(exc).__name__)
        fused: dict[int, float] = {}
        for ranking in rankings:
            for rank, index in enumerate(ranking):
                fused[index] = fused.get(index, 0.0) + 1.0 / (RRF_K + rank + 1)
        ordered = sorted(fused, key=lambda i: (-fused[i], corpus.notes[i]["note_id"]))
        candidates = [corpus.notes[i] for i in ordered]
        hidden = self._hidden_events(candidates, conversation_id, branch_scope)
        hits = []
        for index in ordered:
            note = corpus.notes[index]
            if hidden & set(note.get("source_event_ids") or []):
                continue
            hits.append(_hit(note, fused[index]))
            if len(hits) >= limit:
                break
        return hits

    def _hidden_events(
        self,
        notes: Sequence[dict[str, Any]],
        conversation_id: str,
        branch_scope: Mapping[str, Any] | None,
    ) -> set[str]:
        payloads = [
            {
                "event_id": str(event_id),
                "conversation_id": str(note.get("conversation_id") or ""),
                "storage_scope": self.store.scope,
                "timestamp": float(note.get("occurred_from") or note.get("recorded_from") or 0),
            }
            for note in notes
            for event_id in note.get("source_event_ids") or []
        ]
        if not payloads:
            return set()
        return self._gate(payloads, conversation_id, branch_scope)


def _hit(note: Mapping[str, Any], score: float) -> dict[str, Any]:
    return {
        "note_id": note["note_id"],
        "kind": note.get("kind"),
        "text": note.get("text"),
        "conversation_id": note.get("conversation_id"),
        "occurred_from": note.get("occurred_from"),
        "occurred_to": note.get("occurred_to"),
        "source_event_ids": list(note.get("source_event_ids") or []),
        "source_segment_id": note.get("source_segment_id"),
        "score": round(score, 6),
    }


__all__ = ["NoteRetriever", "read_gate_hidden", "reset_note_retrieval_cache"]
