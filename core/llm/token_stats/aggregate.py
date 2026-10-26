# -*- coding: utf-8 -*-
"""把归一的用量记录聚合成看板需要的分桶结果。

统计口径：
- ``hit_tokens`` / ``miss_tokens`` 都是 ``prompt_tokens`` 的子集，互斥且不重复计入；
- ``total_tokens`` = 输入 + 已记录的输出，缓存命中不会额外加总（避免重复计数）；
- 历史记录没有 ``completion_tokens``，聚合结果里它只累计有记录的调用，
  ``coverage.with_completion`` 给出覆盖率，看板上必须同时展示。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from core.llm.token_stats.costing import COST_COUNT_FIELDS, COST_FLOAT_FIELDS

#: 参与累加的 token 字段（requests 单独计）
TOKEN_FIELDS = (
    "prompt_tokens",
    "hit_tokens",
    "miss_tokens",
    "cache_write_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "total_tokens",
)

#: 成本字段按浮点累加，缺失时是 0.0；「有没有价」由 COST_COUNT_FIELDS 表达
#: 未走计价链路时这些字段都不存在，累加按 0 处理
COST_FLOAT_SET = frozenset(COST_FLOAT_FIELDS)
COST_COUNT_SET = frozenset(COST_COUNT_FIELDS)
SUM_FIELDS = TOKEN_FIELDS + COST_FLOAT_FIELDS + COST_COUNT_FIELDS

#: 空标签的展示名
UNKNOWN_LABEL = "未标注"


def empty_bucket(key: str = "") -> Dict[str, Any]:
    """新建一个空统计桶。"""
    bucket: Dict[str, Any] = {"key": key, "requests": 0}
    for field in SUM_FIELDS:
        bucket[field] = 0.0 if field in COST_FLOAT_SET else 0
    return bucket


def add_record(bucket: Dict[str, Any], record: Dict[str, Any]) -> None:
    """把一条记录累加进桶（缺失字段按 0 计）。"""
    bucket["requests"] += 1
    for field in TOKEN_FIELDS:
        bucket[field] += int(record.get(field) or 0)
    for field in COST_FLOAT_FIELDS:
        bucket[field] += float(record.get(field) or 0.0)
    for field in COST_COUNT_FIELDS:
        bucket[field] += int(record.get(field) or 0)


def finalize_bucket(bucket: Dict[str, Any]) -> Dict[str, Any]:
    """补上缓存合计、命中率与成本口径，返回同一个桶。"""
    cache_total = bucket["hit_tokens"] + bucket["miss_tokens"]
    bucket["cache_total_tokens"] = cache_total
    bucket["hit_rate"] = round(bucket["hit_tokens"] / cache_total, 4) if cache_total > 0 else None
    for cost_field in COST_FLOAT_FIELDS:
        bucket[cost_field] = round(bucket[cost_field], 6)
    # 一条价都没取到时的 cost_total 必须是 None，不能是 0：
    # 0 在看板上会被读成「这阵子没花钱」
    if bucket["cost_priced"] <= 0:
        bucket["cost_total"] = None
    else:
        bucket["cost_total"] = round(bucket["cost_total"], 6)
    bucket["cost_coverage"] = (
        round(bucket["cost_priced"] / bucket["requests"], 4) if bucket["requests"] else None
    )
    return bucket


def _bucket_key(record: Dict[str, Any], field: str) -> str:
    return str(record.get(field) or "") or UNKNOWN_LABEL


def _top_breakdown(records: Iterable[Dict[str, Any]], field: str, top: int) -> List[Dict[str, Any]]:
    """按字段分桶，取总量前 ``top`` 项，其余合并成「其他」。"""
    buckets: Dict[str, Dict[str, Any]] = {}
    for record in records:
        key = _bucket_key(record, field)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = empty_bucket(key)
            buckets[key] = bucket
        add_record(bucket, record)

    ordered = sorted(buckets.values(), key=lambda item: item["total_tokens"], reverse=True)
    if top > 0 and len(ordered) > top:
        rest = empty_bucket("其他")
        for bucket in ordered[top:]:
            rest["requests"] += bucket["requests"]
            for token_field in SUM_FIELDS:
                if token_field in COST_FLOAT_SET:
                    rest[token_field] += float(bucket.get(token_field) or 0.0)
                else:
                    rest[token_field] += int(bucket.get(token_field) or 0)
        ordered = ordered[:top] + [rest]
    return [finalize_bucket(bucket) for bucket in ordered]


def coverage_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """统计记录覆盖情况：首末时间、输出 token 与缓存字段的覆盖率。"""
    if not records:
        return {
            "records": 0,
            "with_completion": 0,
            "with_cache": 0,
            "first_ts": None,
            "last_ts": None,
        }
    timestamps = [record["ts"] for record in records]
    return {
        "records": len(records),
        "with_completion": sum(1 for r in records if r["has_completion"]),
        "with_cache": sum(1 for r in records if r["has_cache"]),
        "first_ts": min(timestamps).isoformat(),
        "last_ts": max(timestamps).isoformat(),
    }


def aggregate(
    records: List[Dict[str, Any]],
    granularity: str = "day",
    top: int = 20,
    include_channel: bool = False,
) -> Dict[str, Any]:
    """按时间粒度 + 多维度聚合记录。

    ``include_channel`` 打开后额外给一张「按采购渠道」的分布——同一个模型
    直连官方与经聚合网关的价格不同，渠道维度是成本看板的必要拆分。
    """
    bucket_field = "month" if granularity == "month" else "date"

    totals = empty_bucket("合计")
    series_map: Dict[str, Dict[str, Any]] = {}
    for record in records:
        add_record(totals, record)
        key = record[bucket_field]
        bucket = series_map.get(key)
        if bucket is None:
            bucket = empty_bucket(key)
            series_map[key] = bucket
        add_record(bucket, record)

    series = [finalize_bucket(series_map[key]) for key in sorted(series_map.keys())]
    result = {
        "granularity": "month" if granularity == "month" else "day",
        "totals": finalize_bucket(totals),
        "series": series,
        "by_model": _top_breakdown(records, "model", top),
        "by_provider": _top_breakdown(records, "provider", top),
        "by_key": _top_breakdown(records, "key_id", top),
        "by_source": _top_breakdown(records, "source", top),
        "coverage": coverage_summary(records),
    }
    if include_channel:
        result["by_channel"] = _top_breakdown(records, "cost_channel", top)
    return result


def match_record(
    record: Dict[str, Any],
    start: str = "",
    end: str = "",
    model: str = "",
    provider: str = "",
) -> bool:
    """判断记录是否命中筛选条件（日期为闭区间）。"""
    date = record["date"]
    if start and date < start:
        return False
    if end and date > end:
        return False
    if model and record["model"] != model:
        return False
    if provider and record["provider"] != provider:
        return False
    return True


def pick_label(record: Dict[str, Any], field: str) -> Optional[str]:
    """取记录里用于筛选下拉框的字段值。"""
    return record.get(field)
