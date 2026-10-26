# -*- coding: utf-8 -*-
"""价目表数据模型：单价条目、峰谷时段与目录查询。

单价一律按「每 token」存，币种默认 USD。厂商价格页多用「每 1M tokens」，
换算在抓取侧完成，这里不做二次解释。

目录键（``key``）用的是**对外公布的模型标识**，不是厂商名拼接：
- ``deepseek/deepseek-v4-flash`` → 经 OpenRouter 托管下单的那条链路
- ``deepseek-v4-flash``          → 直连 DeepSeek 官方 API 的那条链路

两者是同一个模型的不同采购渠道、价格不同，必须各自成条，不能归一。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

#: 价格来源
SOURCE_OPENROUTER = "openrouter"
SOURCE_DEEPSEEK_OFFICIAL = "deepseek_official"
SOURCE_MANUAL = "manual"


def normalize_model_id(value: Any) -> str:
    """归一模型标识：去空白、转小写，保留 ``:free`` 这类真实影响价格的后缀。"""
    text = str(value or "").strip().lower()
    return " ".join(text.split())


@dataclass(frozen=True)
class PeakSchedule:
    """峰谷时段表。``hour_ranges`` 起点含、终点不含，按 ``timezone`` 解释。"""

    timezone_name: str = "UTC"
    weekdays: Tuple[int, ...] = (1, 2, 3, 4, 5)
    hour_ranges: Tuple[Tuple[int, int], ...] = ((1, 4), (6, 10))

    def is_peak(self, moment: Optional[datetime]) -> bool:
        """判断某时刻是否落在峰时；无时区信息或无排期按非峰处理。"""
        if moment is None or not self.hour_ranges:
            return False
        local = moment.astimezone(timezone.utc) if self.timezone_name == "UTC" else moment
        if local.isoweekday() not in self.weekdays:
            return False
        return any(start <= local.hour < end for start, end in self.hour_ranges)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timezone": self.timezone_name,
            "weekdays": list(self.weekdays),
            "hour_ranges": [list(pair) for pair in self.hour_ranges],
        }

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> Optional["PeakSchedule"]:
        if not isinstance(raw, dict):
            return None
        try:
            ranges = tuple(
                (int(pair[0]), int(pair[1]))
                for pair in (raw.get("hour_ranges") or [])
                if len(pair) == 2
            )
            return cls(
                timezone_name=str(raw.get("timezone") or "UTC"),
                weekdays=tuple(int(d) for d in (raw.get("weekdays") or [1, 2, 3, 4, 5])),
                hour_ranges=ranges,
            )
        except (TypeError, ValueError, IndexError):
            return None


@dataclass(frozen=True)
class TokenPrice:
    """一个模型标识对应的一档单价。缺字段表示「不知道」，按 None 处理而不是 0。"""

    key: str
    currency: str = "USD"
    input: Optional[float] = None
    output: Optional[float] = None
    cache_read: Optional[float] = None
    cache_write: Optional[float] = None
    #: 峰时替换价；只有厂商确有峰谷差时才有值
    peak_input: Optional[float] = None
    peak_output: Optional[float] = None
    peak_cache_read: Optional[float] = None
    schedule: Optional[PeakSchedule] = None
    source: str = ""
    source_url: str = ""
    note: str = ""

    @property
    def has_peak(self) -> bool:
        """是否配了峰时价（配了才谈峰谷，否则排期形同虚设）。"""
        return any(
            value is not None for value in (self.peak_input, self.peak_output, self.peak_cache_read)
        )

    def tier_for(self, moment: Optional[datetime]) -> Dict[str, Optional[float]]:
        """按请求时刻取该用的一档价，返回 input / output / cache_read / cache_write。"""
        use_peak = self.schedule is not None and self.has_peak and self.schedule.is_peak(moment)
        if use_peak:
            return {
                "input": self.peak_input if self.peak_input is not None else self.input,
                "output": self.peak_output if self.peak_output is not None else self.output,
                "cache_read": (
                    self.peak_cache_read if self.peak_cache_read is not None else self.cache_read
                ),
                "cache_write": self.cache_write,
            }
        return {
            "input": self.input,
            "output": self.output,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
        }

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "key": self.key,
            "currency": self.currency,
            "input": self.input,
            "output": self.output,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
            "peak_input": self.peak_input,
            "peak_output": self.peak_output,
            "peak_cache_read": self.peak_cache_read,
            "schedule": self.schedule.to_dict() if self.schedule else None,
            "source": self.source,
            "source_url": self.source_url,
            "note": self.note,
        }
        return payload

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "TokenPrice":
        def _num(name: str) -> Optional[float]:
            value = raw.get(name)
            try:
                return None if value is None else float(value)
            except (TypeError, ValueError):
                return None

        return cls(
            key=str(raw.get("key") or ""),
            currency=str(raw.get("currency") or "USD"),
            input=_num("input"),
            output=_num("output"),
            cache_read=_num("cache_read"),
            cache_write=_num("cache_write"),
            peak_input=_num("peak_input"),
            peak_output=_num("peak_output"),
            peak_cache_read=_num("peak_cache_read"),
            schedule=PeakSchedule.from_dict(raw.get("schedule")),
            source=str(raw.get("source") or ""),
            source_url=str(raw.get("source_url") or ""),
            note=str(raw.get("note") or ""),
        )


@dataclass
class PriceCatalog:
    """模型标识 → 单价的目录，附带同步元信息。"""

    prices: Dict[str, TokenPrice] = field(default_factory=dict)
    synced_at: Optional[str] = None
    #: 每个来源的抓取结果（ok / failed / skipped 与原因），看板据此显示健康度
    sources: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    #: 厂商价格页里的峰谷原文，供人工核对排期有没有过期
    schedule_note: str = ""

    def __len__(self) -> int:
        return len(self.prices)

    def get(self, model_id: Any) -> Optional[TokenPrice]:
        """精确取一条。"""
        return self.prices.get(normalize_model_id(model_id))

    def suffix_matches(self, model_id: Any) -> List[TokenPrice]:
        """按最后一段名字匹配（``deepseek-v4-flash`` 命中 ``deepseek/deepseek-v4-flash``）。"""
        target = normalize_model_id(model_id)
        if not target:
            return []
        return [price for key, price in self.prices.items() if key.split("/")[-1] == target]

    def search(self, keyword: str = "", limit: int = 50) -> List[TokenPrice]:
        """按关键字模糊查目录，供看板核对「这条价是从哪来的」。"""
        needle = normalize_model_id(keyword)
        hits = [price for key, price in self.prices.items() if not needle or needle in key]
        return sorted(hits, key=lambda price: price.key)[:limit]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "synced_at": self.synced_at,
            "sources": self.sources,
            "schedule_note": self.schedule_note,
            "prices": [price.to_dict() for price in self.prices.values()],
        }

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> "PriceCatalog":
        raw = raw or {}
        entries: Iterable[Dict[str, Any]] = raw.get("prices") or []
        prices: Dict[str, TokenPrice] = {}
        for item in entries:
            if not isinstance(item, dict):
                continue
            price = TokenPrice.from_dict(item)
            if price.key:
                prices[price.key] = price
        return cls(
            prices=prices,
            synced_at=raw.get("synced_at"),
            sources=raw.get("sources") if isinstance(raw.get("sources"), dict) else {},
            schedule_note=str(raw.get("schedule_note") or ""),
        )
