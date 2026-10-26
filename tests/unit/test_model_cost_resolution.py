# -*- coding: utf-8 -*-
"""用量成本计算链路的单元测试（归属解析 → 单条计价 → 聚合 → 接口）。

最要紧的三件事：
1. 同一模型「直连官方」与「经网关」必须落到不同价上；
2. 匹配不唯一就不出价，并给出候选，不许猜一个把成本算错；
3. 「没有价」全程保持 None，不能在任何一层退化成 0。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.llm.token_stats import build_overview
from core.llm.token_stats.costing import (
    cost_coverage,
    cost_totals,
    price_records,
    unpriced_breakdown,
)
from core.llm.token_stats.pricing import snapshot as snapshot_module
from core.llm.token_stats.pricing import sync as sync_module
from core.llm.token_stats.pricing.cost import compute_record_cost, convert, cost_of_record
from core.llm.token_stats.pricing.models import PeakSchedule, PriceCatalog, TokenPrice
from core.llm.token_stats.pricing.resolve import match_price

#: 官方直连价与网关托管价刻意不同，用来证明两条渠道不会互相顶掉
_OFFICIAL = TokenPrice(
    key="deepseek-v4-flash",
    input=1.5e-7,
    output=6e-7,
    cache_read=3e-9,
    source="deepseek_official",
)
_GATEWAY = TokenPrice(
    key="deepseek/deepseek-v4-flash",
    input=1.4e-7,
    output=2.8e-7,
    cache_read=2e-8,
    source="openrouter",
)
_PAID = TokenPrice(key="minimax/minimax-m3", input=1e-7, output=1e-6, cache_read=1e-8)


def _catalog() -> PriceCatalog:
    prices = [
        _OFFICIAL,
        _GATEWAY,
        _PAID,
        TokenPrice(key="z-ai/glm-4.5", input=1e-7, output=1e-6),
        TokenPrice(key="anthropic/claude-only-x", input=1e-7, output=1e-6),
        TokenPrice(key="vendor-a/dupe", input=1e-7, output=1e-6),
        TokenPrice(key="vendor-b/dupe", input=1e-7, output=1e-6),
    ]
    return PriceCatalog(prices={p.key: p for p in prices}, synced_at="2026-10-24T10:00:00+08:00")


# ==================== 渠道归属 ====================


def test_exact_id_beats_same_named_gateway_entry():
    match = match_price(_catalog(), "deepseek-v4-flash")
    assert (match.how, match.channel) == ("exact", "direct")
    assert match.price.cache_read == 3e-9


def test_slashed_id_is_a_different_channel_not_an_alias():
    match = match_price(_catalog(), "deepseek/deepseek-v4-flash")
    assert (match.how, match.channel) == ("exact", "deepseek")
    assert match.price.cache_read == 2e-8


def test_key_id_prefix_selects_vendor_channel():
    match = match_price(_catalog(), "glm-4.5", key_id="z-ai:aveline")
    assert (match.how, match.channel) == ("key_vendor", "z-ai")
    # 关掉该口径后只能退到末段唯一匹配
    off = match_price(_catalog(), "glm-4.5", "z-ai:aveline", {"vendor_from_key_prefix": False})
    assert off.how == "unique_suffix"


def test_ambiguous_suffix_returns_candidates_and_no_price():
    match = match_price(_catalog(), "dupe")
    assert match.how == "ambiguous"
    assert match.price is None
    assert match.candidates == ["vendor-a/dupe", "vendor-b/dupe"]


def test_free_suffix_prices_zero_only_when_paid_entry_exists():
    match = match_price(_catalog(), "minimax/minimax-m3:free")
    assert match.how == "free_suffix"
    assert (match.price.input, match.price.output) == (0.0, 0.0)
    # 陌生模型的 :free 不白送；开关关掉后付费型号也不再计零
    assert match_price(_catalog(), "unknown-model:free").how == "missing"
    assert (
        match_price(_catalog(), "minimax/minimax-m3:free", config={"price_free_suffix": False}).how
        == "missing"
    )


def test_empty_inputs_are_unpriced():
    assert match_price(_catalog(), "").how == "missing"
    assert match_price(PriceCatalog(), "deepseek-v4-flash").how == "missing"


# ==================== 单条计价 ====================


def test_cost_splits_hit_miss_write_and_output():
    price = TokenPrice(key="m", input=1e-7, output=6e-7, cache_read=5e-9, cache_write=2.5e-7)
    record = {
        "prompt_tokens": 1000,
        "hit_tokens": 600,
        "miss_tokens": 400,
        "cache_write_tokens": 100,
        "completion_tokens": 200,
    }
    cost = compute_record_cost(record, price)
    assert cost.cache_read == pytest.approx(600 * 5e-9)
    # 写缓存价更高，先从 miss 里拆出来单算，不重复计一遍
    assert cost.input == pytest.approx(300 * 1e-7)
    assert cost.cache_write == pytest.approx(100 * 2.5e-7)
    assert cost.output == pytest.approx(200 * 6e-7)
    assert cost.priced is True and cost.partial is False
    assert cost.unpriced_tokens == 0


def test_no_price_stays_none_and_counts_gap():
    cost = compute_record_cost({"prompt_tokens": 10, "completion_tokens": 5}, None)
    assert cost.total is None
    assert cost.priced is False
    assert cost.unpriced_tokens == 15


def test_legacy_record_charges_whole_prompt_as_input():
    price = TokenPrice(key="m", input=1e-7, output=1e-6, cache_read=1e-9)
    cost = compute_record_cost({"prompt_tokens": 100, "hit_tokens": 0, "miss_tokens": 0}, price)
    assert cost.input == pytest.approx(100 * 1e-7)
    assert cost.cache_read == 0.0


def test_partial_only_counts_tokens_the_vendor_price_page_lacks():
    """老记录没有 completion 字段是历史空洞，不该报成「有量无价」。"""
    price = TokenPrice(key="m", input=1e-7, output=1e-6)
    cost = compute_record_cost({"prompt_tokens": 100, "miss_tokens": 100}, price)
    assert cost.output == 0.0
    assert cost.unpriced_tokens == 0
    # 缺输入价才真的算缺口
    only_output = compute_record_cost(
        {"prompt_tokens": 100, "miss_tokens": 100}, TokenPrice(key="m", output=1e-6)
    )
    assert only_output.total is None
    assert only_output.unpriced_tokens == 100


def test_missing_cache_read_falls_back_to_input_rate():
    price = TokenPrice(key="m", input=1e-7, output=1e-6)
    cost = compute_record_cost({"prompt_tokens": 100, "hit_tokens": 100}, price)
    assert cost.cache_read == pytest.approx(100 * 1e-7)


def test_peak_tier_follows_the_record_timestamp():
    price = TokenPrice(
        key="m",
        input=1e-7,
        peak_input=2e-7,
        schedule=PeakSchedule(hour_ranges=((1, 4),)),
    )
    peak = compute_record_cost(
        {
            "prompt_tokens": 100,
            "miss_tokens": 100,
            "ts": datetime(2026, 10, 26, 2, tzinfo=timezone.utc),
        },
        price,
    )
    off = compute_record_cost(
        {
            "prompt_tokens": 100,
            "miss_tokens": 100,
            "ts": datetime(2026, 10, 25, 2, tzinfo=timezone.utc),
        },
        price,
    )
    assert (peak.tier, peak.input) == ("peak", pytest.approx(100 * 2e-7))
    assert (off.tier, off.input) == ("off_peak", pytest.approx(100 * 1e-7))


def test_same_model_different_channel_costs_differ():
    record = {"prompt_tokens": 1000, "hit_tokens": 1000, "miss_tokens": 0}
    catalog = _catalog()
    direct, direct_match = cost_of_record({**record, "model": "deepseek-v4-flash"}, catalog)
    gateway, gateway_match = cost_of_record(
        {**record, "model": "deepseek/deepseek-v4-flash"}, catalog
    )
    assert direct_match.channel == "direct" and gateway_match.channel == "deepseek"
    assert gateway.cache_read > direct.cache_read


def test_convert_keeps_none_and_applies_rate():
    assert convert(None, "CNY", 7.0) is None
    assert convert(1.0, "CNY", 7.0) == pytest.approx(7.0)
    assert convert(1.0, "USD", 7.0) == 1.0


# ==================== 摊平与汇总 ====================


def _records() -> list:
    return [
        {
            "model": "deepseek-v4-flash",
            "key_id": "deepseek:aveline",
            "prompt_tokens": 1000,
            "hit_tokens": 1000,
            "miss_tokens": 0,
            "completion_tokens": None,
            "cost_priced": 0,
        },
        {"model": "dupe", "key_id": "", "prompt_tokens": 500, "hit_tokens": 0, "miss_tokens": 500},
        {"model": "unknown", "key_id": "", "prompt_tokens": 100, "hit_tokens": 100},
    ]


def test_price_records_flattens_cost_columns():
    rows = price_records(_records(), _catalog())
    assert rows[0]["cost_total"] == pytest.approx(1000 * 3e-9)
    assert rows[0]["cost_priced"] == 1
    # 原始记录不能被改坏，日志字段与成本字段各归各
    assert "cost_total" not in _records()[0]
    totals = cost_totals(rows)
    assert totals["currency"] == "USD"
    assert totals["total"] == pytest.approx(rows[0]["cost_total"])


def test_cost_totals_stay_none_when_nothing_is_priced():
    rows = price_records([{"model": "unknown", "prompt_tokens": 10, "miss_tokens": 10}], _catalog())
    totals = cost_totals(rows, {"display_currency": "CNY", "usd_to_cny": 7.0})
    assert all(totals[key] is None for key in ("total", "input", "output", "cache_read"))
    assert totals["currency"] == "CNY"


def test_coverage_and_unpriced_list_report_the_gap():
    rows = price_records(_records(), _catalog())
    cover = cost_coverage(rows)
    assert (cover["requests"], cover["priced_requests"], cover["unpriced_requests"]) == (3, 1, 2)
    assert cover["priced_ratio"] == pytest.approx(1 / 3, abs=1e-4)
    gaps = unpriced_breakdown(rows)
    # 按缺口 token 量排序，并把歧义候选写清楚，供人工补价
    assert [item["model"] for item in gaps] == ["dupe", "unknown"]
    assert gaps[0]["reason"] == "多渠道同名片段，无法确定用哪条价（vendor-a/dupe, vendor-b/dupe）"
    assert gaps[1]["reason"] == "价目表里没有这个模型"


# ==================== 同步不拖慢取数 ====================


async def test_ensure_catalog_returns_before_slow_fetch_completes(monkeypatch, tmp_path):
    """冷启动只等 eager_wait_seconds，抓得慢就先用空目录，不能拖住看板首屏。"""
    # 快照读写分在 sync 与 snapshot 两个模块，两边的路径都要指到临时目录
    for _module in (sync_module, snapshot_module):
        monkeypatch.setattr(_module, "snapshot_path", lambda cfg=None: tmp_path / "pricing.json")

    async def slow(name, conf):
        await asyncio.sleep(5)
        return [], ""

    monkeypatch.setattr(sync_module, "_fetch_source", slow)
    cfg = {
        "enabled": True,
        "eager_wait_seconds": 0.05,
        "refresh_after_seconds": 1,
        "sources": {"openrouter": {"enabled": True, "url": "https://x"}},
    }
    catalog = await sync_module.ensure_catalog(cfg)
    assert catalog.prices == {}
    if sync_module._TASK is not None:
        sync_module._TASK.cancel()


async def test_disabled_pricing_never_touches_network(monkeypatch, tmp_path):
    # 快照读写分在 sync 与 snapshot 两个模块，两边的路径都要指到临时目录
    for _module in (sync_module, snapshot_module):
        monkeypatch.setattr(_module, "snapshot_path", lambda cfg=None: tmp_path / "pricing.json")

    def explode(*a, **k):
        raise AssertionError("关掉计价开关后不应该联网")

    monkeypatch.setattr(sync_module, "sync_once", explode)
    catalog = await sync_module.ensure_catalog({"enabled": False})
    assert catalog.prices == {}


# ==================== 报表与接口 ====================


def _write_log(path: Path) -> Path:
    lines = [
        {
            "timestamp": "2026-10-01T10:00:00+08:00",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "key_id": "deepseek:aveline",
            "source": "chat",
            "prompt_tokens": 1000,
            "hit_tokens": 1000,
            "miss_tokens": 0,
        },
        {
            "timestamp": "2026-10-02T10:00:00+08:00",
            "provider": "other",
            "model": "unknown-model",
            "prompt_tokens": 400,
            "hit_tokens": 0,
            "miss_tokens": 400,
        },
    ]
    path.write_text("\n".join(json.dumps(item) for item in lines) + "\n", encoding="utf-8")
    return path


def test_report_adds_cost_block_and_channel_breakdown(tmp_path):
    log = _write_log(tmp_path / "stats.log")
    data = build_overview(log_path=log, use_cache=False, catalog=_catalog())
    cost = data["cost"]
    assert cost["totals"]["total"] == pytest.approx(1000 * 3e-9)
    assert cost["coverage"]["priced_requests"] == 1
    assert [item["model"] for item in cost["unpriced"]] == ["unknown-model"]
    assert {row["key"] for row in data["by_channel"]} == {"direct", "未标注"}
    # 没价的桶不能给出 0
    unpriced_bucket = next(row for row in data["by_channel"] if row["key"] == "未标注")
    assert unpriced_bucket["cost_total"] is None


def test_report_without_catalog_keeps_old_shape(tmp_path):
    log = _write_log(tmp_path / "stats.log")
    data = build_overview(log_path=log, use_cache=False)
    assert data["cost"] is None
    assert "by_channel" not in data


@pytest.fixture()
def client(monkeypatch, tmp_path):
    import core.llm.token_stats.report as report_module
    import routers.v1.token_stats as router_module

    log = _write_log(tmp_path / "stats.log")
    monkeypatch.setattr(report_module, "get_stats_log_path", lambda: log)

    async def fake_catalog(force: bool = False):
        return _catalog()

    monkeypatch.setattr(router_module, "_catalog_or_none", fake_catalog)
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1")
    return TestClient(app)


def test_router_overview_carries_cost(client):
    payload = client.get("/api/v1/token-stats/overview").json()["data"]
    assert payload["cost"]["coverage"]["priced_requests"] == 1
    assert payload["cost"]["pricing"]["entry_count"] == 7


def test_router_pricing_endpoints(client):
    got = client.get("/api/v1/token-stats/pricing?keyword=deepseek").json()["data"]
    assert got["keyword"] == "deepseek"
    assert [entry["key"] for entry in got["entries"]] == [
        "deepseek-v4-flash",
        "deepseek/deepseek-v4-flash",
    ]
    synced = client.post("/api/v1/token-stats/pricing/sync").json()
    assert synced["status"] == "success"
    assert synced["data"]["entry_count"] == 7


def test_router_overview_survives_pricing_failure(monkeypatch, tmp_path):
    """价目表整体不可用时，用量接口照常出 token 数，只是不出钱。"""
    import core.llm.token_stats.report as report_module
    import routers.v1.token_stats as router_module

    log = _write_log(tmp_path / "stats.log")
    monkeypatch.setattr(report_module, "get_stats_log_path", lambda: log)

    async def broken(force: bool = False):
        return None

    monkeypatch.setattr(router_module, "_catalog_or_none", broken)
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1")
    payload = TestClient(app).get("/api/v1/token-stats/overview").json()
    assert payload["status"] == "success"
    assert payload["data"]["cost"] is None
    assert payload["data"]["totals"]["requests"] == 2
