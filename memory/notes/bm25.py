"""笔记检索用的轻量 BM25（jieba 分词）。

离线实验有一份同类实现（``scripts/experiments/weighted_memory/retrieval/bm25.py``），
生产代码按约定不引用实验目录，这里独立实现、参数一致（k1=1.5, b=0.75）。
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

_TOKEN_RE = re.compile(r"[一-鿿]|[A-Za-z0-9]+")
_STOP = frozenset("的了是我你他她它在吗呢啊吧呀和与就也都还又说")


def tokenize(text: str) -> list[str]:
    """jieba 可用时按词切，否则退到单字 + 英文数字串；都去停用字。"""
    raw = str(text or "").lower()
    try:
        import jieba

        tokens = [t.strip() for t in jieba.lcut(raw)]
    except Exception:  # noqa: BLE001 - 分词器缺失不应让检索整体失败
        tokens = _TOKEN_RE.findall(raw)
    return [t for t in tokens if t and t not in _STOP and not t.isspace() and t.isprintable()]


class BM25:
    def __init__(self, texts: Sequence[str], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.tokens = [tokenize(text) for text in texts]
        self.lengths = [len(items) for items in self.tokens]
        self.avgdl = sum(self.lengths) / len(self.lengths) if self.lengths else 0.0
        df: dict[str, int] = {}
        for items in self.tokens:
            for token in set(items):
                df[token] = df.get(token, 0) + 1
        total = max(len(self.tokens), 1)
        self.idf = {t: math.log(1 + (total - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def rank(self, query: str, limit: int) -> list[int]:
        """返回得分 > 0 的文档下标，按得分降序。"""
        terms = [t for t in tokenize(query) if t in self.idf]
        if not terms:
            return []
        scored = []
        for index, items in enumerate(self.tokens):
            if not items:
                continue
            freq: dict[str, int] = {}
            for token in items:
                freq[token] = freq.get(token, 0) + 1
            norm = self.k1 * (1 - self.b + self.b * self.lengths[index] / (self.avgdl or 1.0))
            score = sum(
                self.idf[t] * freq[t] * (self.k1 + 1) / (freq[t] + norm) for t in terms if t in freq
            )
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [index for _score, index in scored[: max(limit, 0)]]


__all__ = ["BM25", "tokenize"]
