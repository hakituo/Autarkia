"""分段器 v2 的话题深度打分：本地 bge 向量（与梗概检索同一个模型），不调用生成模型。

深度分 = 1 − cos(左侧最多 3 个交换的向量均值, 右侧最多 3 个交换的向量均值)，越大越像换话题。
交换文本：每条消息截 300 字后拼接，总长不超过 512 字。向量按交换首事件 ID 缓存，
同一会话递归二分时不重复编码。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from memory.topology.topic_split import Unit

WINDOW = 3
MESSAGE_CHARS = 300
UNIT_CHARS = 512

Embedder = Callable[[list[str]], Any]


def unit_text(unit: Unit) -> str:
    return "\n".join(str(event.content or "").strip()[:MESSAGE_CHARS] for event in unit)[
        :UNIT_CHARS
    ]


class EmbeddingScorer:
    """可当 ``topic_split.Scorer`` 直接传入；``embedder`` 缺省时运行时取检索同款 bge。"""

    def __init__(self, embedder: Embedder | None = None, *, window: int = WINDOW) -> None:
        self._embedder = embedder
        self.window = window
        self._vectors: dict[str, np.ndarray] = {}
        self.encoded = 0

    def _embed(self, texts: list[str]) -> np.ndarray:
        if self._embedder is None:
            from memory.notes import embeddings

            self._embedder = embeddings.default_embedder()
        matrix = np.asarray(self._embedder(texts), dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms

    def prepare(self, units: Sequence[Unit]) -> None:
        """批量编码尚未缓存的交换（一次会话调用一次即可）。"""
        missing = [unit for unit in units if unit[0].event_id not in self._vectors]
        if not missing:
            return
        vectors = self._embed([unit_text(unit) for unit in missing])
        for unit, vector in zip(missing, vectors):
            self._vectors[unit[0].event_id] = vector
        self.encoded += len(missing)

    def __call__(self, units: Sequence[Unit], index: int) -> float:
        left = units[max(0, index - self.window) : index]
        right = units[index : index + self.window]
        self.prepare([*left, *right])
        mean_left = np.mean([self._vectors[unit[0].event_id] for unit in left], axis=0)
        mean_right = np.mean([self._vectors[unit[0].event_id] for unit in right], axis=0)
        denom = float(np.linalg.norm(mean_left) * np.linalg.norm(mean_right)) or 1.0
        return 1.0 - float(mean_left @ mean_right) / denom


__all__ = ["EmbeddingScorer", "unit_text"]
