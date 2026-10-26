"""C7 端到端：上下文格式化、答案判定与查询执行。"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Sequence

from ..cases import query_evidence_turns
from ..metrics import norm_text
from .bm25 import BM25Index, filter_visible_docs

ANSWER_SYSTEM = (
    "你只能依据提供的记忆片段回答问题。找不到依据就回答“不知道”。"
    "不要编造，不要使用片段之外的信息。回答保持简短。"
)
REFUSAL_MARKERS = ("不知道", "没有", "未提及", "找不到", "无法确定", "不清楚")


def _norm(value: Any) -> str:
    return norm_text(value)


def format_context(docs: Sequence[Mapping[str, Any]]) -> str:
    lines: List[str] = []
    for index, doc in enumerate(docs, start=1):
        sources = ",".join(str(item) for item in doc.get("source_turns") or [])
        lines.append(f"{index}. {doc.get('text')}（来源: {sources}）")
    return "\n".join(lines) if lines else "（无）"


def answer_prompt(question: str, docs: Sequence[Mapping[str, Any]]) -> str:
    return (
        f"记忆片段：\n{format_context(docs)}\n\n"
        f"问题：{question}\n"
        "只输出答案本身；找不到依据就输出“不知道”。"
    )


def judge_answer(query: Mapping[str, Any], answer: str) -> Dict[str, Any]:
    text = _norm(answer)
    if query.get("unanswerable"):
        refused = any(marker in text for marker in REFUSAL_MARKERS)
        return {
            "passed": refused,
            "reason": "refused" if refused else "should_refuse",
        }
    missing = [
        keyword for keyword in query.get("answer_keywords") or [] if _norm(keyword) not in text
    ]
    any_keywords = query.get("answer_keywords_any") or []
    any_missing = bool(any_keywords) and not any(_norm(keyword) in text for keyword in any_keywords)
    forbidden = [
        keyword for keyword in query.get("forbidden_keywords") or [] if _norm(keyword) in text
    ]
    passed = not missing and not any_missing and not forbidden
    return {
        "passed": passed,
        "reason": (
            "ok" if passed else f"missing={missing} any_missing={any_missing} forbidden={forbidden}"
        ),
    }


def run_queries(
    cases: Sequence[Mapping[str, Any]],
    corpus: Mapping[str, List[Dict[str, Any]]],
    client: Any,
    *,
    k: int = 5,
    branch_filter: bool = True,
    max_tokens: int = 220,
    index_factory: Callable[[Sequence[Mapping[str, Any]]], Any] = BM25Index,
) -> List[Dict[str, Any]]:
    """``index_factory`` 决定检索器（默认 BM25；真实集另跑 BM25 + 向量混合）。"""
    rows: List[Dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("id"))
        active = str(case.get("active_branch") or "main")
        docs = corpus.get(case_id, [])
        visible = filter_visible_docs(docs, active) if branch_filter else docs
        index = index_factory(visible)
        sibling_docs = [doc for doc in docs if str(doc.get("branch") or "") != active]
        for query in case.get("queries") or []:
            retrieved = index.search(str(query.get("text") or ""), k)
            cross_line = [
                doc for doc in retrieved if str(doc.get("branch") or "") not in {active, ""}
            ]
            answer = client.chat(
                ANSWER_SYSTEM,
                answer_prompt(str(query.get("text") or ""), retrieved),
                max_tokens=max_tokens,
                json_mode=False,
            ).text
            judged = judge_answer(query, answer)
            retrieved_sources = [
                source for doc in retrieved for source in doc.get("source_turns") or []
            ]
            rows.append(
                {
                    "case_id": case_id,
                    "query_id": query.get("id"),
                    "type": query.get("type"),
                    "query": query.get("text"),
                    "gold_turns": query_evidence_turns(case, query),
                    "retrieved_doc_ids": [doc.get("doc_id") for doc in retrieved],
                    "retrieved_docs": [
                        {
                            "doc_id": doc.get("doc_id"),
                            "source_turns": list(doc.get("source_turns") or []),
                            "branch": doc.get("branch"),
                        }
                        for doc in retrieved
                    ],
                    "retrieved_sources": retrieved_sources,
                    "retrieved_branches": [doc.get("branch") for doc in retrieved],
                    "cross_line_count": len(cross_line),
                    "sibling_docs_in_corpus": len(sibling_docs),
                    "answer": answer,
                    "passed": judged["passed"],
                    "judge_reason": judged["reason"],
                }
            )
    return rows


__all__ = ["answer_prompt", "format_context", "judge_answer", "run_queries"]
