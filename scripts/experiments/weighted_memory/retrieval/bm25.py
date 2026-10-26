"""C7 检索基础：分词、BM25 与分支可见性过滤。"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

import jieba

jieba.setLogLevel(logging.WARNING)

_TOKEN_RE = re.compile(r"[0-9a-zA-Z\u4e00-\u9fff]+")
_STOPWORDS = frozenset(
    {
        "的",
        "了",
        "是",
        "在",
        "和",
        "就",
        "都",
        "也",
        "很",
        "有",
        "吗",
        "呢",
        "吧",
        "啊",
        "这",
        "那",
        "一个",
        "一下",
        "什么",
        "怎么",
        "哪个",
        "哪里",
        "多少",
        "几点",
        "我",
        "你",
        "他",
        "她",
        "它",
    }
)


def tokenize(text: Any) -> List[str]:
    tokens: List[str] = []
    for raw in jieba.lcut(str(text or "").lower()):
        token = raw.strip()
        if not token or token in _STOPWORDS:
            continue
        if not _TOKEN_RE.fullmatch(token):
            continue
        tokens.append(token)
    return tokens


class BM25Index:
    def __init__(
        self, docs: Sequence[Mapping[str, Any]], *, k1: float = 1.5, b: float = 0.75
    ) -> None:
        self.docs = [dict(doc) for doc in docs]
        self.k1 = k1
        self.b = b
        self.tokens = [tokenize(doc.get("text")) for doc in self.docs]
        self.lengths = [len(items) for items in self.tokens]
        self.avgdl = sum(self.lengths) / len(self.lengths) if self.lengths else 0.0
        self.df: Dict[str, int] = {}
        for items in self.tokens:
            for token in set(items):
                self.df[token] = self.df.get(token, 0) + 1
        total = max(len(self.docs), 1)
        self.idf = {
            token: math.log(1 + (total - freq + 0.5) / (freq + 0.5))
            for token, freq in self.df.items()
        }

    def search(
        self, query: str, k: int, *, allow: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        scored: List[tuple[float, int]] = []
        for index, doc in enumerate(self.docs):
            if allow is not None and not allow(doc):
                continue
            score = 0.0
            length = self.lengths[index] or 1
            for token in query_tokens:
                freq = self.tokens[index].count(token)
                if not freq:
                    continue
                idf = self.idf.get(token, 0.0)
                denom = freq + self.k1 * (1 - self.b + self.b * length / (self.avgdl or 1))
                score += idf * freq * (self.k1 + 1) / denom
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda item: (-item[0], str(self.docs[item[1]].get("doc_id"))))
        return [
            {"score": round(score, 4), **self.docs[index]}
            for score, index in scored[: max(k, 0)]
        ]


def filter_visible_docs(
    docs: Sequence[Mapping[str, Any]], active_branch: str
) -> List[Mapping[str, Any]]:
    return [
        doc for doc in docs if str(doc.get("branch") or "") in {active_branch, ""}
    ]


__all__ = ["BM25Index", "filter_visible_docs", "tokenize"]
