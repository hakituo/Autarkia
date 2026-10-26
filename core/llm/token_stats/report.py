# -*- coding: utf-8 -*-
"""组装 dashboard / CLI 需要的完整用量报表。"""

from __future__ import annotations

import copy
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.llm.token_stats.aggregate import (
    aggregate,
    coverage_summary,
    empty_bucket,
    finalize_bucket,
    match_record,
)
from core.llm.token_stats.costing import (
    cost_coverage,
    cost_totals,
    price_records,
    priced_model_rows,
    unpriced_breakdown,
)
from core.llm.token_stats.loader import get_stats_log_path, load_records
from core.llm.token_stats.pricing.models import PriceCatalog
from core.llm.token_stats.pricing.settings import get_pricing_config
from core.llm.token_stats.pricing.sync import pricing_status
from core.utils.time.time_utils import now_iso

#: 未定价模型清单最多列几条
UNPRICED_LIST_LIMIT = 12

#: 价目面板一级放几个在用模型：整张价目表几百条，摊开等于没信息
PRICED_MODEL_LIST_LIMIT = 8

#: 看板刷新会重复读同一份日志，短 TTL 缓存避免每次筛选都重解析 20k+ 行
_CACHE_TTL_SECONDS = 5.0
_CACHE_MAX_ENTRIES = 16
_CACHE: Dict[Tuple[Any, ...], Tuple[float, Dict[str, Any]]] = {}


def clear_cache() -> None:
    """清空报表缓存（测试与手动刷新用）。"""
    _CACHE.clear()


def _date_range(first: str, last: str, granularity: str) -> List[str]:
    """生成连续的时间键（补零用），跨度异常时退回原序列。"""
    try:
        if granularity == "month":
            start = datetime.strptime(first, "%Y-%m")
            end = datetime.strptime(last, "%Y-%m")
        else:
            start = datetime.strptime(first, "%Y-%m-%d")
            end = datetime.strptime(last, "%Y-%m-%d")
    except ValueError:
        return []
    if end < start:
        return []
    keys: List[str] = []
    cursor = start
    while cursor <= end and len(keys) < 1200:
        keys.append(cursor.strftime("%Y-%m" if granularity == "month" else "%Y-%m-%d"))
        if granularity == "month":
            # 月份不能按 31 天步进（1/31 + 31 天会落到 3 月）
            year, month = cursor.year, cursor.month + 1
            if month > 12:
                year, month = year + 1, 1
            cursor = cursor.replace(year=year, month=month, day=1)
        else:
            cursor += timedelta(days=1)
    return keys


def fill_series(
    series: List[Dict[str, Any]],
    granularity: str,
    first: str = "",
    last: str = "",
) -> List[Dict[str, Any]]:
    """把缺失的日期/月份补成 0，便于看板画出连续的柱状图。"""
    if not series:
        return series
    first_key = first or series[0]["key"]
    last_key = last or series[-1]["key"]
    keys = _date_range(first_key, last_key, granularity)
    if not keys:
        return series
    existing = {bucket["key"]: bucket for bucket in series}
    return [existing.get(key) or finalize_bucket(empty_bucket(key)) for key in keys]


def _options(records: List[Dict[str, Any]], field: str) -> List[str]:
    values = {str(record.get(field) or "") for record in records}
    return sorted(value for value in values if value)


def build_overview(
    granularity: str = "day",
    start: str = "",
    end: str = "",
    model: str = "",
    provider: str = "",
    top: int = 20,
    log_path: Optional[Path] = None,
    use_cache: bool = True,
    catalog: Optional[PriceCatalog] = None,
    pricing_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """读取日志 → 过滤 → （有价目表则逐条计价）→ 聚合，返回看板所需的全部数据。

    结果按筛选参数做 5 秒 TTL 缓存：日志是追加写的，看板刷新/切筛选
    时没必要重复解析整份文件；需要绝对最新数据时传 ``use_cache=False``。

    Args:
        catalog: 价目表；不传则完全退回不计价的老行为
        pricing_config: 计价配置；不传时按 YAML 现读
    """
    path = Path(log_path) if log_path is not None else get_stats_log_path()
    cache_key = (
        str(path),
        granularity,
        start,
        end,
        model,
        provider,
        int(top),
        # 价目表重新同步过就要重算，否则新价格要等缓存过期才生效
        catalog.synced_at if catalog is not None else "",
    )
    now = time.monotonic()
    if use_cache:
        cached = _CACHE.get(cache_key)
        if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
            return copy.deepcopy(cached[1])

    data = _build_overview(
        granularity, start, end, model, provider, top, path, catalog, pricing_config
    )
    if use_cache:
        if len(_CACHE) >= _CACHE_MAX_ENTRIES:
            _CACHE.clear()
        _CACHE[cache_key] = (now, data)
        return copy.deepcopy(data)
    return data


def _build_overview(
    granularity: str,
    start: str,
    end: str,
    model: str,
    provider: str,
    top: int,
    path: Path,
    catalog: Optional[PriceCatalog] = None,
    pricing_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """不带缓存的实际计算过程。"""
    all_records = load_records(path)
    matched = [
        record
        for record in all_records
        if match_record(record, start=start, end=end, model=model, provider=provider)
    ]
    # 成本只在读取时算，不写回用量日志：厂商调价后历史用量会自动重新计价
    rows = matched
    cfg: Optional[Dict[str, Any]] = None
    if catalog is not None:
        cfg = pricing_config if pricing_config is not None else get_pricing_config()
        rows = price_records(matched, catalog, cfg)
    data = aggregate(
        rows,
        granularity=granularity,
        top=top,
        include_channel=catalog is not None,
    )
    data["series"] = fill_series(
        data["series"],
        data["granularity"],
        first=start,
        last=end,
    )
    data["cost"] = _cost_block(rows, catalog, cfg)

    all_coverage = coverage_summary(all_records)
    data.update(
        {
            "generated_at": now_iso(),
            "log_path": str(path),
            "log_exists": path.exists(),
            "filters": {
                "granularity": data["granularity"],
                "start": start,
                "end": end,
                "model": model,
                "provider": provider,
            },
            "options": {
                "models": _options(all_records, "model"),
                "providers": _options(all_records, "provider"),
            },
            "archive": {
                "first_ts": all_coverage["first_ts"],
                "last_ts": all_coverage["last_ts"],
                "records": all_coverage["records"],
            },
        }
    )
    return data


def _cost_block(
    rows: List[Dict[str, Any]],
    catalog: Optional[PriceCatalog],
    cfg: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """成本概览块：金额、覆盖率、在用模型价格、待补价清单与价目表健康度。"""
    if catalog is None or cfg is None:
        return None
    return {
        "totals": cost_totals(rows, cfg),
        "coverage": cost_coverage(rows),
        "models": priced_model_rows(rows, catalog, cfg, PRICED_MODEL_LIST_LIMIT),
        "unpriced": unpriced_breakdown(rows, UNPRICED_LIST_LIMIT),
        "pricing": pricing_status(catalog, cfg),
    }
