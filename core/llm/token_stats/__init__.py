# -*- coding: utf-8 -*-
"""LLM token 用量统计（日志读取 → 聚合 → 看板报表）。

数据源：``logs/prompt_cache_stats.log``（JSONL），由
``core.llm.llm_logger.log_llm_usage`` 写入。仅供只读分析，不改动请求链路。
"""

from core.llm.token_stats.aggregate import aggregate
from core.llm.token_stats.loader import (
    get_stats_log_path,
    iter_records,
    load_records,
    normalize_record,
)
from core.llm.token_stats.report import build_overview, fill_series

__all__ = [
    "aggregate",
    "build_overview",
    "fill_series",
    "get_stats_log_path",
    "iter_records",
    "load_records",
    "normalize_record",
]
