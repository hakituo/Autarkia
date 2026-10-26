# -*- coding: utf-8 -*-
"""单条用量记录的成本计算。

计费口径（与用量日志的字段一一对应）：

- ``hit_tokens``            → 缓存命中读价 ``cache_read``；价目表没这一档时退回输入价
- ``miss_tokens``           → 减去 ``cache_write_tokens`` 后按未命中输入价计
- ``cache_write_tokens``    → 单独按写缓存价计（Anthropic / OpenRouter 口径下
                              写缓存是另一档价，且它本身已含在 miss 里，不能再计一遍）
- ``completion_tokens``     → 输出价；``reasoning_tokens`` 视为其子集，不重复加
- 峰谷                      → 按**请求自身时间戳**落到哪一档，而不是按查询时间

**算不出就是 None，不是 0**。这是这条链路上最重要的一条约定：把「没有价」
写成 0，看板上就和「免费模型」长得一模一样，钱会静悄悄地少算。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from core.llm.token_stats.pricing.models import PriceCatalog, TokenPrice
from core.llm.token_stats.pricing.resolve import PriceMatch, match_price


@dataclass
class RecordCost:
    """一条记录的成本构成。

    Attributes:
        total: 成本合计；一段价格都没取到时是 ``None``（区别于 0）
        priced: 是否至少有一段算出了价
        unpriced_tokens: 有 token 但没价可计的量，供看板标注估算范围
    """

    total: Optional[float] = None
    input: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    output: float = 0.0
    #: 用了峰价还是谷价：peak / off_peak / ""（厂商没有峰谷差时为空）
    tier: str = ""
    priced: bool = False
    unpriced_tokens: int = 0

    @property
    def partial(self) -> bool:
        """部分算得出、部分没价——看板要把它和「完全没价」区分开。"""
        return self.priced and self.unpriced_tokens > 0


def _tokens(record: Dict[str, Any], field_name: str) -> Optional[int]:
    """取 token 数；字段缺失返回 None（区别于 0，输出侧的历史空洞靠它识别）。"""
    value = record.get(field_name)
    if value is None or value == "":
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def compute_record_cost(
    record: Dict[str, Any],
    price: Optional[TokenPrice],
    moment: Optional[datetime] = None,
) -> RecordCost:
    """按单价算一条记录的成本。``price`` 为空时返回全未计价结果。"""
    cost = RecordCost()
    if price is None:
        # 整条都没价：把可数的 token 都记成未定价，便于看板汇总缺口
        for field_name in ("prompt_tokens", "completion_tokens"):
            cost.unpriced_tokens += _tokens(record, field_name) or 0
        return cost

    when = moment if isinstance(moment, datetime) else record.get("ts")
    if not isinstance(when, datetime):
        when = None
    tier = price.tier_for(when)
    if price.schedule is not None and price.has_peak:
        cost.tier = "peak" if price.schedule.is_peak(when) else "off_peak"

    input_rate = tier.get("input")
    write_rate = tier.get("cache_write")
    output_rate = tier.get("output")
    # 没配读价就退回输入价：宁可估高，也不要把命中当成免费
    read_rate = tier.get("cache_read")
    if read_rate is None:
        read_rate = input_rate

    prompt = _tokens(record, "prompt_tokens") or 0
    hit = _tokens(record, "hit_tokens") or 0
    miss = _tokens(record, "miss_tokens") or 0
    write = _tokens(record, "cache_write_tokens") or 0
    completion = _tokens(record, "completion_tokens")

    cache_total = hit + miss
    # 老记录没有缓存字段（hit+miss=0），整段输入按未命中价计
    cached_read = hit
    cached_write = min(write, miss) if cache_total > 0 else write
    uncached_input = prompt if cache_total <= 0 else max(0, miss - cached_write)

    segments = (
        ("cache_read", cached_read, read_rate),
        ("input", uncached_input, input_rate),
        # 厂商不单收写缓存费时，这部分已经落在 uncached_input 里了，不重复计
        ("cache_write", cached_write if write_rate is not None else 0, write_rate),
        ("output", completion or 0, output_rate),
    )
    for name, tokens, rate in segments:
        if tokens <= 0:
            continue
        if rate is None:
            cost.unpriced_tokens += tokens
            continue
        value = tokens * float(rate)
        setattr(cost, name, value)
        cost.priced = True

    if cost.priced:
        cost.total = cost.input + cost.cache_read + cost.cache_write + cost.output
    return cost


def cost_of_record(
    record: Dict[str, Any],
    catalog: PriceCatalog,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[RecordCost, PriceMatch]:
    """一步到位：解析渠道 → 取价 → 算成本。"""
    match = match_price(catalog, record.get("model"), record.get("key_id"), config)
    moment = record.get("ts")
    if not isinstance(moment, datetime):
        moment = None
    return compute_record_cost(record, match.price, moment), match


def convert(amount: Optional[float], currency: str, usd_to_cny: float) -> Optional[float]:
    """把 USD 成本换算成展示币种；``None`` 原样传下去，不折算成 0。"""
    if amount is None:
        return None
    if str(currency or "USD").upper() == "CNY":
        return amount * float(usd_to_cny or 1.0)
    return amount
