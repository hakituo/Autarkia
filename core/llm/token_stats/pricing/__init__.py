# -*- coding: utf-8 -*-
"""模型价目表与用量成本计算（LLM 看板的成本层）。

对外只用两个动作：

- :func:`get_catalog` —— 异步取当前价目表（过期自动后台重抓，不阻塞取数）
- :func:`cost_of_record` —— 用价目表现算一条记录的成本

成本**不落进用量日志**，每次读的时候按当前价目表现算。这样厂商调价、
补上人工覆盖之后，历史用量会自动重新计价，不需要回填日志、也不会出现
「日志里存的是三个月前的价」。
"""

from core.llm.token_stats.pricing.cost import (
    RecordCost,
    compute_record_cost,
    convert,
    cost_of_record,
)
from core.llm.token_stats.pricing.models import (
    PriceCatalog,
    TokenPrice,
    normalize_model_id,
)
from core.llm.token_stats.pricing.resolve import PriceMatch, match_price
from core.llm.token_stats.pricing.settings import get_pricing_config, snapshot_path
from core.llm.token_stats.pricing.snapshot import (
    load_catalog,
    read_snapshot,
    reset_cache,
    write_snapshot,
)
from core.llm.token_stats.pricing.sync import (
    ensure_catalog,
    is_stale,
    pricing_status,
    sync_once,
)

__all__ = [
    "PriceCatalog",
    "PriceMatch",
    "RecordCost",
    "TokenPrice",
    "compute_record_cost",
    "convert",
    "cost_of_record",
    "ensure_catalog",
    "get_catalog",
    "get_pricing_config",
    "is_stale",
    "load_catalog",
    "match_price",
    "normalize_model_id",
    "pricing_status",
    "read_snapshot",
    "reset_cache",
    "snapshot_path",
    "sync_once",
    "write_snapshot",
]


async def get_catalog(force_refresh: bool = False) -> PriceCatalog:
    """取价目表：``force_refresh=True`` 时立刻重抓并等结果。"""
    return await ensure_catalog(force=force_refresh)
