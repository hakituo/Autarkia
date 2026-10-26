"""混合检索：BM25 排名 + 向量相似度排名，用 RRF 融合（与 BM25Index 同接口）。

真实聊天口语化、问句与原话几乎不共享词（「住在哪个城市」vs「重庆这边也多」），
纯 BM25 约四成题目检不到证据。向量模型由调用方注入（生产同款 bge-small-zh），
单测可传假向量函数，不依赖模型文件。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .bm25 import BM25Index

Embedder = Callable[[list[str]], Sequence[Sequence[float]]]

#: RRF 常数；60 是文献惯用值，对排名靠后的文档衰减平缓
RRF_K = 60
#: 每路各取前 N 名参与融合
CANDIDATES_PER_ROUTE = 50


def _normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(float(x) * float(x) for x in vector)) or 1.0
    return [float(x) / norm for x in vector]


class HybridIndex:
    def __init__(self, docs: Sequence[Mapping[str, Any]], embedder: Embedder) -> None:
        self.docs = [dict(doc) for doc in docs]
        self._bm25 = BM25Index(self.docs)
        self._embedder = embedder
        texts = [str(doc.get("text") or "") for doc in self.docs]
        self._vectors = [_normalize(v) for v in embedder(texts)] if texts else []

    def _dense_ranking(self, query: str) -> list[int]:
        if not self._vectors:
            return []
        q = _normalize(self._embedder([query])[0])
        scores = [sum(a * b for a, b in zip(q, vec)) for vec in self._vectors]
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
        return order[:CANDIDATES_PER_ROUTE]

    def search(self, query: str, k: int) -> list[dict[str, Any]]:
        position = {str(doc.get("doc_id")): index for index, doc in enumerate(self.docs)}
        sparse = [
            position[str(hit.get("doc_id"))]
            for hit in self._bm25.search(query, CANDIDATES_PER_ROUTE)
            if str(hit.get("doc_id")) in position
        ]
        fused: dict[int, float] = {}
        for ranking in (sparse, self._dense_ranking(query)):
            for rank, index in enumerate(ranking):
                fused[index] = fused.get(index, 0.0) + 1.0 / (RRF_K + rank + 1)
        order = sorted(fused, key=lambda i: (-fused[i], str(self.docs[i].get("doc_id"))))[
            : max(k, 0)
        ]
        return [{"score": round(fused[i], 6), **self.docs[i]} for i in order]


__all__ = ["CANDIDATES_PER_ROUTE", "RRF_K", "Embedder", "HybridIndex"]
