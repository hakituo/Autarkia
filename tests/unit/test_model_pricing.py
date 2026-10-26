# -*- coding: utf-8 -*-
"""模型价目表层（配置、来源解析、快照同步）的单元测试。

三条最容易出错的口径：
1. 同一模型「直连官方」与「经聚合网关」是两条不同价，不能归一；
2. 解析不出来就不给价，不许悄悄落成 0（0 和免费在看板上长得一样）；
3. 抓取失败必须保留上一份快照，价格页改版不能把已有价格抹掉。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from core.llm.token_stats.pricing import settings as settings_module
from core.llm.token_stats.pricing import snapshot as snapshot_module
from core.llm.token_stats.pricing import sync as sync_module
from core.llm.token_stats.pricing.models import PeakSchedule, TokenPrice, normalize_model_id
from core.llm.token_stats.pricing.sources import parse_deepseek_official, parse_openrouter

#: 官网价格表的最小复刻：行首指标带 rowspan，行尾金额个数 == 模型列数
_DS_HTML = "\n".join(
    [
        "<table>",
        "<tr><td>MODEL</td><td>deepseek-flash (1)</td><td>deepseek-v4-pro</td></tr>",
        '<tr><td rowspan="6">PRICING (2)</td><td rowspan="6">1M INPUT TOKENS (CACHE HIT)</td>'
        "<td>OFF-PEAK</td><td>$0.003</td><td>$0.022</td></tr>",
        "<tr><td>PEAK</td><td>$0.006</td><td>$0.044</td></tr>",
        '<tr><td colspan="2">1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td>'
        "<td>$0.15</td><td>$0.66</td></tr>",
        "<tr><td>PEAK</td><td>$0.3</td><td>$1.32</td></tr>",
        '<tr><td colspan="2">1M OUTPUT TOKENS</td><td>OFF-PEAK</td>'
        "<td>$0.6</td><td>$1.98</td></tr>",
        "<tr><td>PEAK</td><td>$1.2</td><td>$3.96</td></tr>",
        "<tr><td colspan=4>Peak hours are 01:00 - 04:00 and 06:00 - 10:00 UTC, "
        "Monday through Friday.</td></tr>",
        "</table>",
    ]
)

_DS_CONFIG = {
    "model_aliases": {"deepseek-flash": "deepseek-v4-flash"},
    "off_peak_divisor": 2.0,
    "peak_schedule": {
        "timezone": "UTC",
        "weekdays": [1, 2, 3, 4, 5],
        "hour_ranges": [[1, 4], [6, 10]],
    },
}


@pytest.fixture(autouse=True)
def _isolate_pricing_caches():
    """配置缓存与快照缓存都是进程级的，用例前后都要清。"""
    settings_module.reset_config_cache()
    snapshot_module.reset_cache()
    sync_module._TASK = None
    yield
    settings_module.reset_config_cache()
    snapshot_module.reset_cache()
    sync_module._TASK = None


@pytest.fixture()
def project_sandbox(monkeypatch, tmp_path):
    """把配置与快照路径都指向临时目录，避免读写项目里的真文件。"""
    (tmp_path / "config" / "yaml").mkdir(parents=True)
    monkeypatch.setattr(settings_module, "get_project_root", lambda: tmp_path)
    # 快照读写分在 sync 与 snapshot 两个模块，两边的路径都要指到临时目录
    for _module in (sync_module, snapshot_module):
        monkeypatch.setattr(_module, "snapshot_path", lambda cfg=None: tmp_path / "pricing.json")
    return tmp_path


# ==================== 配置 ====================


def test_missing_config_falls_back_to_defaults(project_sandbox):
    cfg = settings_module.get_pricing_config()
    assert cfg["sources"]["openrouter"]["enabled"] is True
    assert cfg["refresh_after_seconds"] == 21600
    assert cfg["display_currency"] == "USD"


def test_yaml_merges_over_defaults(project_sandbox):
    path = settings_module.config_path()
    path.write_text(
        "pricing:\n"
        "  refresh_after_seconds: 60\n"
        "  sources:\n"
        "    deepseek_official:\n"
        "      enabled: false\n",
        encoding="utf-8",
    )
    settings_module.reset_config_cache()
    cfg = settings_module.get_pricing_config()
    assert cfg["refresh_after_seconds"] == 60
    # 只覆盖写出来的键，同级其余字段仍从默认值继承
    assert cfg["sources"]["deepseek_official"]["enabled"] is False
    assert cfg["sources"]["deepseek_official"]["url"].startswith("https://")


def test_broken_yaml_does_not_break_dashboard(project_sandbox):
    settings_module.config_path().write_text("pricing: [oops\n", encoding="utf-8")
    settings_module.reset_config_cache()
    assert settings_module.get_pricing_config()["enabled"] is True


# ==================== 数据模型 ====================


def test_normalize_keeps_price_bearing_suffix():
    assert (
        normalize_model_id(" DeepSeek/DeepSeek-V4-Flash:Free ") == "deepseek/deepseek-v4-flash:free"
    )


def test_peak_schedule_is_utc_and_half_open():
    schedule = PeakSchedule(
        timezone_name="UTC", weekdays=(1, 2, 3, 4, 5), hour_ranges=((1, 4), (6, 10))
    )
    monday_2am = datetime(2026, 10, 26, 2, 0, tzinfo=timezone.utc)
    assert schedule.is_peak(monday_2am) is True
    # 区间终点不含、周末不算、无时刻不算
    assert schedule.is_peak(monday_2am.replace(hour=4)) is False
    assert schedule.is_peak(datetime(2026, 10, 25, 2, 0, tzinfo=timezone.utc)) is False
    assert schedule.is_peak(None) is False


def test_tier_for_switches_between_peak_rows():
    price = TokenPrice(
        key="deepseek-v4-flash",
        input=1e-7,
        output=2e-7,
        cache_read=5e-9,
        peak_input=2e-7,
        peak_output=4e-7,
        peak_cache_read=1e-8,
        schedule=PeakSchedule(),
    )
    assert price.has_peak is True
    assert price.tier_for(datetime(2026, 10, 26, 2, 0, tzinfo=timezone.utc))["input"] == 2e-7
    assert price.tier_for(datetime(2026, 10, 25, 2, 0, tzinfo=timezone.utc))["input"] == 1e-7
    # 没配峰谷差的厂商不该被强行套上排期
    plain = TokenPrice(key="m", input=1e-7)
    assert plain.has_peak is False
    assert plain.tier_for(datetime(2026, 10, 26, 2, 0, tzinfo=timezone.utc))["input"] == 1e-7


# ==================== 来源解析 ====================


def test_parse_openrouter_uses_published_per_token_prices():
    payload = {
        "data": [
            {
                "id": "DeepSeek/DeepSeek-Chat",
                "pricing": {
                    "prompt": "0.000001",
                    "completion": "0.000002",
                    "input_cache_read": "0.00000002",
                    "input_cache_write": "",
                    "internal_reasoning": "0.0000005",
                },
            },
            {"id": "no-price-model", "pricing": {}},
            {"id": "", "pricing": {"prompt": "0.000001"}},
        ]
    }
    entries = parse_openrouter(payload, "https://x/models")
    assert [e.key for e in entries] == ["deepseek/deepseek-chat"]
    entry = entries[0]
    # 这个接口本来就是「每 token」价，不做换算
    assert entry.input == pytest.approx(1e-6)
    assert entry.cache_read == pytest.approx(2e-8)
    assert entry.cache_write is None
    assert "reasoning" in entry.note
    with pytest.raises(ValueError):
        parse_openrouter({"data": []}, "https://x/models")


def test_parse_openrouter_drops_variable_price_sentinel():
    """网关用 ``-1`` 表示「价格随实际路由的模型而定」，不能当价用（会算出负成本）。"""
    payload = {
        "data": [
            {"id": "openrouter/auto", "pricing": {"prompt": "-1", "completion": "-1"}},
            {"id": "vendor/partial", "pricing": {"prompt": "0.000001", "input_cache_read": "-1"}},
        ]
    }
    entries = parse_openrouter(payload, "https://x/models")
    assert [e.key for e in entries] == ["vendor/partial"]
    assert entries[0].cache_read is None
    assert "浮动" in entries[0].note


def test_parse_deepseek_official_matrix():
    entries, note = parse_deepseek_official(_DS_HTML, "https://x/pricing", _DS_CONFIG)
    by_key = {entry.key: entry for entry in entries}
    assert set(by_key) == {"deepseek-v4-flash", "deepseek-v4-pro"}
    flash = by_key["deepseek-v4-flash"]
    assert flash.input == pytest.approx(0.15 / 1e6)
    assert flash.cache_read == pytest.approx(0.003 / 1e6)
    assert flash.output == pytest.approx(0.6 / 1e6)
    assert flash.peak_input == pytest.approx(0.3 / 1e6)
    # 官方不单收写缓存费：保持 None，让计价侧把这段折进未命中输入
    assert flash.cache_write is None
    assert flash.source == "deepseek_official"
    assert flash.schedule is not None
    assert note.startswith("Peak hours are")


def test_parse_deepseek_fills_missing_tier_by_divisor():
    """页面只印一档时按倍数补另一档，不能把单档当常价。"""
    single = (
        "<table>"
        "<tr><td>MODEL</td><td>deepseek-flash</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE HIT)</td><td>OFF-PEAK</td><td>$0.003</td></tr>"
        "<tr><td>1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td><td>$0.15</td></tr>"
        "<tr><td>1M OUTPUT TOKENS</td><td>OFF-PEAK</td><td>$0.6</td></tr>"
        "</table>"
    )
    entries, _ = parse_deepseek_official(single, "u", _DS_CONFIG)
    assert entries[0].input == pytest.approx(0.15 / 1e6)
    assert entries[0].peak_input == pytest.approx(0.3 / 1e6)


def test_parse_deepseek_rejects_restructured_page():
    with pytest.raises(ValueError):
        parse_deepseek_official("<table><tr><td>价格</td></tr></table>", "u", _DS_CONFIG)


# ==================== 快照与同步 ====================


def test_snapshot_roundtrip_and_no_temp_leftovers(project_sandbox):
    from core.llm.token_stats.pricing.models import PriceCatalog

    catalog = PriceCatalog(
        prices={"a/b": TokenPrice(key="a/b", input=1e-7, schedule=PeakSchedule())},
        synced_at="2026-10-24T10:00:00+08:00",
        sources={"openrouter": {"ok": True, "entries": 1}},
    )
    sync_module.write_snapshot(catalog)
    loaded, mtime = sync_module.read_snapshot()
    assert mtime is not None
    assert loaded.synced_at == catalog.synced_at
    assert loaded.prices["a/b"].schedule == PeakSchedule()
    assert list((project_sandbox).glob(".pricing-*")) == []


async def test_successful_source_replaces_stale_entries(project_sandbox, monkeypatch):
    """抓成功的来源以最新列表为准：厂商下线或改了口径的条目要跟着消失，否则错价永远留在目录里。"""
    from core.llm.token_stats.pricing.models import PriceCatalog

    sync_module.write_snapshot(
        PriceCatalog(
            prices={
                "openrouter/gone": TokenPrice(
                    key="openrouter/gone", input=1e-7, source="openrouter"
                ),
                "official/keep": TokenPrice(
                    key="official/keep", input=1e-7, source="deepseek_official"
                ),
            },
            synced_at="2026-01-01T00:00:00+08:00",
        )
    )
    cfg = settings_module.get_pricing_config()
    cfg["sources"]["deepseek_official"]["enabled"] = False

    async def fake(name, conf):
        return [TokenPrice(key="openrouter/live", input=2e-7, source=name)], ""

    monkeypatch.setattr(sync_module, "_fetch_source", fake)
    catalog = await sync_module.sync_once(cfg)
    assert set(catalog.prices) == {"openrouter/live", "official/keep"}


async def test_disabled_source_keeps_previous_prices(project_sandbox, monkeypatch):
    from core.llm.token_stats.pricing.models import PriceCatalog

    sync_module.write_snapshot(
        PriceCatalog(
            prices={"old/model": TokenPrice(key="old/model", input=1e-7, source="openrouter")},
            synced_at="2026-01-01T00:00:00+08:00",
        )
    )

    async def boom(name, cfg):
        raise RuntimeError("页面改版")

    monkeypatch.setattr(sync_module, "_fetch_source", boom)
    catalog = await sync_module.sync_once(settings_module.get_pricing_config())
    assert "old/model" in catalog.prices
    assert catalog.sources["openrouter"]["ok"] is False
    assert "页面改版" in catalog.sources["openrouter"]["error"]


async def test_sync_marks_disabled_source_and_manual_wins(project_sandbox, monkeypatch):
    cfg = settings_module.get_pricing_config()
    cfg["sources"]["deepseek_official"]["enabled"] = False
    # 人工覆盖按「每 token」写，与快照存储口径一致
    cfg["overrides"] = {"openrouter/deepseek-chat": {"input": 5e-7, "output": 1e-6}}

    async def fake(name, conf):
        return [TokenPrice(key="openrouter/deepseek-chat", input=9e-7, source=name)], ""

    monkeypatch.setattr(sync_module, "_fetch_source", fake)
    catalog = await sync_module.sync_once(cfg)
    # 人工覆盖优先于抓取结果
    assert catalog.prices["openrouter/deepseek-chat"].input == pytest.approx(5e-7)
    assert catalog.prices["openrouter/deepseek-chat"].source == "manual"
    assert catalog.sources["deepseek_official"]["skipped"] is True
    assert catalog.sources["openrouter"]["ok"] is True


def test_is_stale_and_status_report(project_sandbox):
    from core.llm.token_stats.pricing.models import PriceCatalog

    cfg = settings_module.get_pricing_config()
    fresh = PriceCatalog(synced_at=datetime.now(timezone.utc).isoformat())
    assert sync_module.is_stale(fresh, cfg) is False
    # 从没同步过、或同步时间读不出来，都算过期（要重抓）
    assert sync_module.is_stale(PriceCatalog(), cfg) is True
    assert sync_module.is_stale(PriceCatalog(synced_at="bad"), cfg) is True
    status = sync_module.pricing_status(fresh, cfg)
    assert status["stale"] is False
    assert status["display_currency"] == "USD"
    assert json.dumps(status, ensure_ascii=False)
