"""C6/C7 评分指标：文本匹配与统计量按职责分在 text / stats。"""

from __future__ import annotations

from .stats import (
    answer_metrics,
    arm_extraction_metrics,
    bootstrap_ci,
    cross_line_stats,
    ndcg_at_k,
    recall_at_k,
    retrieval_metrics,
    wilson_ci,
)
from .text import (
    gold_coverage,
    keywords_match,
    norm_text,
    normalize_zh_numbers,
    parse_failure_rate,
    provenance_stats,
    supported_note_stats,
)

__all__ = [
    "answer_metrics",
    "arm_extraction_metrics",
    "bootstrap_ci",
    "cross_line_stats",
    "gold_coverage",
    "keywords_match",
    "ndcg_at_k",
    "norm_text",
    "normalize_zh_numbers",
    "parse_failure_rate",
    "provenance_stats",
    "recall_at_k",
    "retrieval_metrics",
    "supported_note_stats",
    "wilson_ci",
]
