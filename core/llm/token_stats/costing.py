# -*- coding: utf-8 -*-
"""把价目表套到用量记录上，产出可供聚合累加的成本字段。

设计要点：聚合器只认「数值字段求和」，所以成本先摊平成每条记录上的若干
数值列，再交给 ``aggregate`` 按时间桶 / 模型 / 渠道累加。摊平的代价是
「没有价」这个状态会退化成 0，因此额外落两列计数——
``cost_priced``（算出价的请求数）与 ``cost_unpriced_tokens``（有量无价的 token 数），
桶级再由 ``finalize_bucket`` 把一条价都没取到的桶的 ``cost_total`` 改回 ``None``。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from core.llm.token_stats.pricing.cost import convert, cost_of_record
from core.llm.token_stats.pricing.models import PriceCatalog
from core.llm.token_stats.pricing.resolve import HOW_FREE, reason_text
from core.llm.token_stats.pricing.settings import get_pricing_config

#: 成本段：(记录摊平后的列名, RecordCost 上的属性名, 对外 JSON 键)
COST_SEGMENTS: Tuple[Tuple[str, str, str], ...] = (
    ("cost_total", "total", "total"),
    ("cost_input", "input", "input"),
    ("cost_cache_read", "cache_read", "cache_read"),
    ("cost_cache_write", "cache_write", "cache_write"),
    ("cost_output", "output", "output"),
)
COST_FLOAT_FIELDS = tuple(field for field, _, _ in COST_SEGMENTS)
COST_COUNT_FIELDS = (
    "cost_priced",
    "cost_partial",
    "cost_unpriced_tokens",
    "cost_peak_requests",
)

#: 厂商价格页普遍按「每 1M tokens」标价，看板对外也按这个口径给
_PER_MILLION = 1_000_000.0


def price_records(
    records: Iterable[Dict[str, Any]],
    catalog: PriceCatalog,
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """给每条记录附上成本字段，返回新列表（不改传入的原始记录）。"""
    priced: List[Dict[str, Any]] = []
    for record in records:
        cost, match = cost_of_record(record, catalog, config)
        row = dict(record)
        for field_name, attr, _ in COST_SEGMENTS:
            row[field_name] = float(getattr(cost, attr) or 0.0)
        row["cost_priced"] = 1 if cost.priced else 0
        row["cost_partial"] = 1 if cost.partial else 0
        row["cost_unpriced_tokens"] = int(cost.unpriced_tokens or 0)
        row["cost_peak_requests"] = 1 if cost.tier == "peak" else 0
        row["cost_channel"] = match.channel or ""
        row["cost_price_key"] = match.price.key if match.price else ""
        row["cost_price_source"] = match.price.source if match.price else ""
        row["cost_match"] = match.how
        row["cost_candidates"] = match.candidates
        priced.append(row)
    return priced


def cost_totals(
    rows: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """把逐条成本汇总成看板顶部的金额块，并按展示币种折算。

    一条价都没取到时全部金额回 ``None``，不能回 0——看板上 0 意味着「没花钱」，
    而实际情况是「不知道花了多少钱」，两者必须能区分。
    """
    cfg = config or get_pricing_config()
    currency = str(cfg.get("display_currency") or "USD").upper()
    usd_to_cny = float(cfg.get("usd_to_cny") or 1.0)
    priced = [row for row in rows if row.get("cost_priced")]
    result: Dict[str, Any] = {"currency": currency, "usd_to_cny": usd_to_cny}
    for field, _, json_key in COST_SEGMENTS:
        if not priced:
            result[json_key] = None
            continue
        amount = sum(float(row.get(field) or 0.0) for row in priced)
        result[json_key] = convert(round(amount, 6), currency, usd_to_cny)
    return result


def cost_coverage(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """成本覆盖率：多少请求算出了价、多少 token 没价。"""
    requests = len(rows)
    priced = sum(1 for row in rows if row.get("cost_priced"))
    partial = sum(1 for row in rows if row.get("cost_partial"))
    return {
        "requests": requests,
        "priced_requests": priced,
        "unpriced_requests": requests - priced,
        "partial_requests": partial,
        "priced_ratio": round(priced / requests, 4) if requests else None,
        "unpriced_tokens": sum(int(row.get("cost_unpriced_tokens") or 0) for row in rows),
        "peak_requests": sum(1 for row in rows if row.get("cost_peak_requests")),
    }


def priced_model_rows(
    rows: List[Dict[str, Any]],
    catalog: PriceCatalog,
    config: Optional[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    """「用得最多的模型 + 它的单价」清单，看板价目面板的一级列表。

    整张价目表有几百条，但真正在花钱的通常就那几个；把几百条摊开等于没信息。
    同一个模型可能被解析到不同价目键（渠道不同、名称归一多条候选），
    取出现次数最多的那个键，单价按「每 1M tokens」给——厂商官网就是这个口径，
    按 token 写出来全是零，读的人只会以为没花钱。
    """
    cfg = config or get_pricing_config()
    currency = str(cfg.get("display_currency") or "USD").upper()
    usd_to_cny = float(cfg.get("usd_to_cny") or 1.0)

    buckets: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not row.get("cost_priced"):
            continue
        model = str(row.get("model") or "") or "未标注"
        entry = buckets.setdefault(model, {"requests": 0, "cost_total": 0.0, "keys": {}, "how": {}})
        entry["requests"] += 1
        entry["cost_total"] += float(row.get("cost_total") or 0.0)
        key = str(row.get("cost_price_key") or "")
        if key:
            entry["keys"][key] = entry["keys"].get(key, 0) + 1
            entry["how"][key] = str(row.get("cost_match") or "")

    ordered = sorted(buckets.items(), key=lambda pair: pair[1]["requests"], reverse=True)
    result: List[Dict[str, Any]] = []
    for model, item in ordered[:limit]:
        key = max(item["keys"].items(), key=lambda pair: pair[1])[0] if item["keys"] else ""
        price = catalog.prices.get(key)
        # 免费档是解析时现造的零价条目，本来就不在价目表里；查不到键不等于没价
        is_free = price is None and key and item["how"].get(key) == HOW_FREE
        rates = {
            name: _per_million(price, name, currency, usd_to_cny)
            for name in ("input", "cache_read", "cache_write", "output")
        }
        if is_free:
            rates = {name: 0.0 for name in rates}
        result.append(
            {
                "model": model,
                "requests": item["requests"],
                "cost_total": convert(round(item["cost_total"], 6), currency, usd_to_cny),
                "price_key": key,
                "source": price.source if price else ("free 档" if is_free else ""),
                "currency": currency,
                "has_peak": bool(price.has_peak) if price else False,
                "per_1m": rates,
            }
        )
    return result


def _per_million(price: Any, name: str, currency: str, usd_to_cny: float) -> Optional[float]:
    """某个分档的每 1M 单价（折算到展示币种）；没这一档的价就是 None。"""
    rate = getattr(price, name, None) if price is not None else None
    if rate is None:
        return None
    return convert(round(float(rate) * _PER_MILLION, 6), currency, usd_to_cny)


def unpriced_breakdown(rows: List[Dict[str, Any]], limit: int = 12) -> List[Dict[str, Any]]:
    """没取到价的模型清单，按未定价 token 量排序——看板的「待补价」列表。

    ``cost_match`` 为 ``free_suffix`` 的条目已经在价目表里显式判成零价，
    不算缺口，不列进来。
    """
    buckets: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if row.get("cost_priced"):
            continue
        model = str(row.get("model") or "") or "未标注"
        entry = buckets.setdefault(
            model,
            {
                "model": model,
                "channel": str(row.get("cost_channel") or ""),
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "how": str(row.get("cost_match") or ""),
                "candidates": list(row.get("cost_candidates") or []),
            },
        )
        entry["requests"] += 1
        entry["prompt_tokens"] += int(row.get("prompt_tokens") or 0)
        completion = row.get("completion_tokens")
        entry["completion_tokens"] += int(completion or 0) if completion is not None else 0
    ordered = sorted(
        buckets.values(),
        key=lambda item: item["prompt_tokens"] + item["completion_tokens"],
        reverse=True,
    )
    for item in ordered:
        item["reason"] = reason_text(item["how"], item["candidates"])
    return ordered[:limit]
