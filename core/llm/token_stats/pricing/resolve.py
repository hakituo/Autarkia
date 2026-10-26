# -*- coding: utf-8 -*-
"""用量记录 → 价格条目的归属解析。

同一个模型经不同渠道下单价格不同，所以「记录对应哪条价」必须判准：

- ``deepseek-v4-flash`` + ``key_id=deepseek:aveline`` → 直连官方，用官方价
- ``deepseek/deepseek-v4-flash``                     → 经 OpenRouter 托管，用托管价

解析严格按确定性优先级走，**匹配不唯一时不猜**：返回 ambiguous 并带上候选，
让看板如实标出「这条没价」，而不是随便挑一个把成本算错。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.llm.token_stats.pricing.models import PriceCatalog, TokenPrice, normalize_model_id

#: 匹配方式，按确定性从高到低
HOW_EXACT = "exact"
HOW_KEY_VENDOR = "key_vendor"
HOW_GATEWAY = "gateway"
HOW_UNIQUE_SUFFIX = "unique_suffix"
#: 带 ``:free`` 后缀、按同型号免费档计零；结果里会显式标出来，不混进「没价」
HOW_FREE = "free_suffix"
HOW_AMBIGUOUS = "ambiguous"
HOW_MISSING = "missing"

#: 聚合网关的免费档后缀（OpenRouter 用 ``:free`` 表示零价路由）
FREE_SUFFIXES = (":free", ":noop")


@dataclass
class PriceMatch:
    """一条记录的价格匹配结果。"""

    price: Optional[TokenPrice] = None
    how: str = HOW_MISSING
    requested_model: str = ""
    channel: str = ""
    candidates: List[str] = field(default_factory=list)


def channel_from_key_id(key_id: Any, enabled: bool = True) -> str:
    """从 ``key_id`` 前缀取渠道名：``deepseek:aveline`` → ``deepseek``。"""
    if not enabled:
        return ""
    text = str(key_id or "").strip()
    if not text or ":" not in text:
        return ""
    return text.split(":", 1)[0].strip().lower()


def _channel_of(price: TokenPrice) -> str:
    """价格条目所属渠道：带斜杠的是网关渠道名，否则直连官方。"""
    return price.key.rsplit("/", 1)[0] if "/" in price.key else "direct"


def _qualify(channel: str, model_key: str) -> str:
    return f"{channel}/{model_key}" if channel and model_key else model_key


def _free_variant_price(
    catalog: PriceCatalog, model_key: str, config: Dict[str, Any]
) -> Optional[TokenPrice]:
    """``foo:free`` 这类免费档按零价计，前提是同型号的付费条目在价目表里存在。

    只认「后缀 + 同型号付费条目存在」这个组合，避免把一个完全陌生的模型
    因为名字里带 free 就白送。命中的条目 ``how`` 会标成 ``free_suffix``，
    看板上和「没取到价」分开展示。
    """
    if not config.get("price_free_suffix", True):
        return None
    index = model_key.find(":")
    if index <= 0:
        return None
    suffix = model_key[index:]
    if suffix not in FREE_SUFFIXES:
        return None
    base = catalog.get(model_key[:index])
    if base is None:
        return None
    return TokenPrice(
        key=model_key,
        currency=base.currency,
        input=0.0,
        output=0.0,
        cache_read=0.0,
        cache_write=0.0,
        source=base.source,
        source_url=base.source_url,
        note="免费路由档，按零价计（同型号付费条目存在）",
    )


def match_price(
    catalog: PriceCatalog,
    model: Any,
    key_id: Any = "",
    config: Optional[Dict[str, Any]] = None,
) -> PriceMatch:
    """查一条记录该用哪条价。

    优先级：原样精确 → key_id 渠道限定 → 网关渠道限定 → 末段唯一匹配。
    末段匹配到多条时判为 ambiguous，不出价。
    """
    cfg = config or {}
    model_key = normalize_model_id(model)
    match = PriceMatch(requested_model=model_key)
    if not model_key or not catalog.prices:
        return match

    entry = catalog.get(model_key)
    if entry is not None:
        match.price = entry
        match.how = HOW_EXACT
        match.channel = _channel_of(entry)
        return match

    key_channel = channel_from_key_id(key_id, bool(cfg.get("vendor_from_key_prefix", True)))
    gateway_channel = str(cfg.get("slashed_model_vendor") or "openrouter")
    probes: List[Tuple[str, str]] = []
    if key_channel:
        probes.append((key_channel, HOW_KEY_VENDOR))
    if gateway_channel:
        probes.append((gateway_channel, HOW_GATEWAY))

    tried: List[str] = []
    for channel, how in probes:
        qualified = _qualify(channel, model_key)
        if qualified in tried:
            continue
        tried.append(qualified)
        entry = catalog.get(qualified)
        if entry is not None:
            match.price = entry
            match.how = how
            match.channel = channel
            return match

    suffix = model_key.split("/")[-1]
    free_price = _free_variant_price(catalog, model_key, cfg)
    if free_price is not None:
        match.price = free_price
        match.how = HOW_FREE
        match.channel = _channel_of(free_price)
        return match

    hits = [p for p in catalog.suffix_matches(suffix) if p.key != model_key]
    if len(hits) == 1:
        match.price = hits[0]
        match.how = HOW_UNIQUE_SUFFIX
        match.channel = _channel_of(hits[0])
        return match
    if len(hits) > 1:
        match.how = HOW_AMBIGUOUS
        match.candidates = sorted(p.key for p in hits)
        return match

    match.how = HOW_MISSING
    return match


#: 未定价原因措辞
_REASON_TEXTS = {
    HOW_MISSING: "价目表里没有这个模型",
    HOW_AMBIGUOUS: "多渠道同名片段，无法确定用哪条价",
}


def reason_text(how: str, candidates: Optional[List[str]] = None) -> str:
    """未定价原因的看板措辞；多渠道歧义时列出候选，便于人工确认该用哪条价。"""
    if how == HOW_AMBIGUOUS and candidates:
        return f"{_REASON_TEXTS[HOW_AMBIGUOUS]}（{', '.join(candidates[:3])}）"
    return _REASON_TEXTS.get(how, "价格字段缺失")
