# -*- coding: utf-8 -*-
"""「在用模型价格」一级列表的单元测试。

看板价目面板只该看到真正在花钱的几个模型：按用量排序、单价按每 1M tokens 给；
没价的模型留给二级清单，免费档要显式标零而不是「无价」。
"""

from __future__ import annotations

import pytest

from core.llm.token_stats.costing import price_records, priced_model_rows
from core.llm.token_stats.pricing.models import PriceCatalog, TokenPrice

_OFFICIAL = TokenPrice(
    key="deepseek-v4-flash",
    input=1.5e-7,
    output=6e-7,
    cache_read=3e-9,
    peak_input=3e-7,
    source="deepseek_official",
)
_PAID_BASE = TokenPrice(
    key="minimax/minimax-m3.1-flash", input=1e-7, output=6e-7, source="openrouter"
)


def _catalog() -> PriceCatalog:
    return PriceCatalog(prices={price.key: price for price in (_OFFICIAL, _PAID_BASE)})


def _records(model: str, count: int = 1) -> list:
    return [
        {
            "model": model,
            "key_id": "",
            "prompt_tokens": 1000,
            "hit_tokens": 0,
            "miss_tokens": 1000,
            "completion_tokens": 100,
        }
        for _ in range(count)
    ]


def _cfg(currency: str = "USD", rate: float = 1.0) -> dict:
    return {"display_currency": currency, "usd_to_cny": rate, "price_free_suffix": True}


def test_rows_ranked_by_usage_and_capped():
    rows = price_records(
        _records("deepseek-v4-flash", 3) + _records("minimax/minimax-m3.1-flash"),
        _catalog(),
        _cfg(),
    )
    ranked = priced_model_rows(rows, _catalog(), _cfg(), limit=8)
    assert [item["model"] for item in ranked] == ["deepseek-v4-flash", "minimax/minimax-m3.1-flash"]
    assert ranked[0]["requests"] == 3
    assert len(priced_model_rows(rows, _catalog(), _cfg(), limit=1)) == 1


def test_unit_price_given_per_million():
    """单价按每 1M tokens 给：按 token 写出来全是零，读的人只会以为没花钱。"""
    rows = price_records(_records("deepseek-v4-flash"), _catalog(), _cfg())
    item = priced_model_rows(rows, _catalog(), _cfg(), limit=8)[0]
    assert item["per_1m"]["input"] == pytest.approx(0.15)
    assert item["per_1m"]["cache_read"] == pytest.approx(0.003)
    # 没这一档的价保持 None，不能退化成 0
    assert item["per_1m"]["cache_write"] is None
    assert item["has_peak"] is True
    assert item["source"] == "deepseek_official"


def test_unpriced_model_left_to_secondary_list():
    """没价的模型（自研 M2-her 这类）不进一级列表，交给二级的待补价清单。"""
    rows = price_records(_records("deepseek-v4-flash") + _records("M2-her"), _catalog(), _cfg())
    assert [item["model"] for item in priced_model_rows(rows, _catalog(), _cfg(), limit=8)] == [
        "deepseek-v4-flash"
    ]


def test_free_tier_reports_zero_not_missing():
    """免费档是解析时现造的零价条目，本来就不在价目表里，不能显示成「无单价」。"""
    rows = price_records(_records("minimax/minimax-m3.1-flash:free"), _catalog(), _cfg())
    item = priced_model_rows(rows, _catalog(), _cfg(), limit=8)[0]
    assert item["per_1m"]["input"] == 0.0
    assert item["source"] == "free 档"


def test_unit_prices_follow_display_currency():
    cfg = _cfg("CNY", 7.0)
    rows = price_records(_records("deepseek-v4-flash"), _catalog(), cfg)
    item = priced_model_rows(rows, _catalog(), cfg, limit=8)[0]
    assert item["currency"] == "CNY"
    assert item["per_1m"]["input"] == pytest.approx(1.05)
