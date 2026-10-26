"""C6/C7 统计指标：Wilson / bootstrap、Recall@k、nDCG@k、答案与跨线统计。"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .text import gold_coverage, parse_failure_rate, provenance_stats, supported_note_stats


def arm_extraction_metrics(
    notes: Sequence[Mapping[str, Any]],
    gold_facts_by_case: Mapping[str, Mapping[str, Mapping[str, Any]]],
    usage: Mapping[str, Any],
) -> Dict[str, Any]:
    notes_by_case: Dict[str, List[Mapping[str, Any]]] = {}
    for note in notes:
        notes_by_case.setdefault(str(note.get("case_id")), []).append(note)

    matched = 0
    total = 0
    for case_id, gold_facts in gold_facts_by_case.items():
        result = gold_coverage(notes_by_case.get(case_id, []), gold_facts)
        matched += result["matched"]
        total += result["denominator"]

    supported = supported_note_stats(notes, _flatten(gold_facts_by_case))
    provenance = provenance_stats(notes)
    return {
        "notes": supported["notes"],
        "gold_coverage": {
            "matched": matched,
            "denominator": total,
            "rate": round(matched / total, 4) if total else None,
            "ci95": wilson_ci(matched, total),
        },
        "supported_notes": supported,
        "provenance": provenance,
        "parse_failure_rate": parse_failure_rate(notes),
        "usage": dict(usage),
    }


def _flatten(
    gold_facts_by_case: Mapping[str, Mapping[str, Mapping[str, Any]]]
) -> Dict[str, Mapping[str, Any]]:
    flattened: Dict[str, Mapping[str, Any]] = {}
    for gold_facts in gold_facts_by_case.values():
        flattened.update(gold_facts)
    return flattened


def wilson_ci(success: int, total: int, z: float = 1.96) -> Optional[List[float]]:
    if total <= 0:
        return None
    phat = success / total
    denom = 1 + z * z / total
    center = (phat + z * z / (2 * total)) / denom
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total) / denom
    return [round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)]


def bootstrap_ci(
    values: Sequence[float],
    *,
    n_boot: int = 2000,
    seed: int = 20261025,
) -> Dict[str, Any]:
    if not values:
        return {"mean": None, "ci95": None, "n": 0}
    rng = random.Random(seed)
    means: List[float] = []
    for _ in range(n_boot):
        sample = [values[rng.randrange(len(values))] for _ in range(len(values))]
        means.append(sum(sample) / len(sample))
    means.sort()
    low = means[int(0.025 * (len(means) - 1))]
    high = means[int(0.975 * (len(means) - 1))]
    return {
        "mean": round(sum(values) / len(values), 4),
        "ci95": [round(low, 4), round(high, 4)],
        "n": len(values),
    }


def ndcg_at_k(relevances: Sequence[int], k: int, gold_count: Optional[int] = None) -> float:
    """理想排序按金标证据数构造（不是按已检索到的文档），一条相关都没检到记 0。

    ``gold_count`` 缺省时退回旧口径（只用已检索文档排理想序），仅为兼容调用方。
    """
    if k <= 0:
        return 0.0
    top = list(relevances[:k])
    dcg = sum(rel / math.log2(index + 2) for index, rel in enumerate(top))
    if gold_count is not None:
        ideal = [1] * min(max(int(gold_count), 0), k)
    else:
        ideal = sorted(relevances, reverse=True)[:k]
    idcg = sum(rel / math.log2(index + 2) for index, rel in enumerate(ideal))
    if idcg <= 0:
        return 0.0
    return round(min(dcg / idcg, 1.0), 4)


def recall_at_k(
    retrieved_sources: Any,
    gold_sources: Any,
    k: int,
) -> Optional[float]:
    gold = {str(item) for item in gold_sources}
    if not gold:
        return None
    retrieved = {str(item) for item in retrieved_sources}
    hit = len(gold & retrieved)
    return round(hit / len(gold), 4)


def retrieval_metrics(rows: Sequence[Mapping[str, Any]], k: int) -> Dict[str, Any]:
    recall_values: List[float] = []
    ndcg_values: List[float] = []
    for row in rows:
        gold = {str(item) for item in row.get("gold_turns") or []}
        if not gold:
            continue
        recall = recall_at_k(row.get("retrieved_sources") or [], gold, k)
        if recall is not None:
            recall_values.append(recall)
        relevances = []
        for doc in row.get("retrieved_docs") or []:
            sources = {str(item) for item in doc.get("source_turns") or []}
            relevances.append(1 if sources & gold else 0)
        ndcg_values.append(ndcg_at_k(relevances, k, gold_count=len(gold)))
    return {
        "k": k,
        "recall": bootstrap_ci(recall_values),
        "ndcg": bootstrap_ci(ndcg_values),
        "denominator": len(recall_values),
    }


def answer_metrics(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    def _rate(subset: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        total = len(subset)
        passed = sum(1 for row in subset if row.get("passed"))
        return {
            "passed": passed,
            "denominator": total,
            "rate": round(passed / total, 4) if total else None,
            "ci95": wilson_ci(passed, total),
        }

    by_type: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        by_type.setdefault(str(row.get("type") or "unknown"), []).append(row)
    return {
        "overall": _rate(rows),
        "by_type": {key: _rate(items) for key, items in sorted(by_type.items())},
        "knowledge_update": _rate(
            [row for row in rows if row.get("type") == "knowledge_update"]
        ),
        "refusal": _rate([row for row in rows if row.get("type") == "refusal"]),
        "temporal": _rate([row for row in rows if row.get("type") == "temporal"]),
    }


def cross_line_stats(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    violations = sum(int(row.get("cross_line_count") or 0) for row in rows)
    queries_with_risk = sum(
        1 for row in rows if int(row.get("sibling_docs_in_corpus") or 0) > 0
    )
    return {
        "cross_line_evidence": violations,
        "queries_with_sibling_corpus": queries_with_risk,
        "denominator": len(rows),
    }


__all__ = [
    "answer_metrics",
    "arm_extraction_metrics",
    "bootstrap_ci",
    "cross_line_stats",
    "ndcg_at_k",
    "recall_at_k",
    "retrieval_metrics",
    "wilson_ci",
]
