#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证模型价目表同步与用量成本实时计算。

四组检查（全部走真实来源与真实日志，不落任何测试数据）：
1. 抓取：两个价格源都出条目、快照能落盘并复读、峰谷排期在位；
2. 单位量级：任何一档「每 1M tokens」价必须在合理区间——
   这一条专防把每 token 价当每 1M 价（或反过来）算出百万倍的偏差；
3. 计价：真实日志的覆盖率、分段求和一致、无价必须是 None 而不是 0；
4. 渠道：同一模型的直连价与网关价不能被打成同一条。

运行：
    venv_cpu\\Scripts\\python.exe tests\\scripts\\llm\\verify_model_pricing.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

#: 每 1M tokens 的合理价区间（美元）：远低于此说明单位被除过，远高于此说明没除
_PER_MILLION_LOW = 0.0001
_PER_MILLION_HIGH = 2000.0


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _approx(left: float, right: float, tol: float = 1e-6) -> bool:
    return abs(left - right) <= max(tol, abs(right) * 1e-6)


def verify_sync() -> object:
    """真抓一轮：来源出条目、快照落盘、排期在位。"""
    from core.llm.token_stats.pricing import get_pricing_config, load_catalog, sync_once
    from core.llm.token_stats.pricing.settings import snapshot_path

    cfg = get_pricing_config(force_reload=True)
    _check(bool(cfg.get("enabled")), "model_pricing.yaml 里 pricing.enabled 应为 true")
    catalog = asyncio.run(sync_once(cfg))
    _check(len(catalog.prices) > 200, f"价目表条目过少: {len(catalog.prices)}")
    ok_sources = [name for name, st in catalog.sources.items() if st.get("ok")]
    _check(len(ok_sources) >= 2, f"至少两个来源应抓取成功，实际: {catalog.sources}")
    _check(catalog.synced_at is not None, "同步时间应写入快照")
    _check(load_catalog(snapshot_path(cfg)).prices, "快照应能复读回来")

    with_schedule = [p for p in catalog.prices.values() if p.schedule is not None and p.has_peak]
    _check(bool(with_schedule), "厂商峰谷价应至少解析出一条带排期的条目")
    print(
        f"[OK] 抓取：{len(catalog.prices)} 条价目，来源 {', '.join(ok_sources)}，"
        f"峰谷条目 {len(with_schedule)} 条"
    )
    return catalog


def verify_units(catalog) -> None:
    """单位量级：每 1M 价必须落在合理区间，且命中价不该明显高于未命中价。"""
    bad_high, bad_low, upside = [], [], []
    for price in catalog.prices.values():
        for name in ("input", "output", "cache_read", "cache_write"):
            value = getattr(price, name)
            if value is None or value == 0:
                continue
            per_million = value * 1_000_000
            if per_million > _PER_MILLION_HIGH:
                bad_high.append(f"{price.key}.{name}={per_million:,.2f}/1M")
            elif per_million < _PER_MILLION_LOW:
                bad_low.append(f"{price.key}.{name}={per_million:.6f}/1M")
        if (
            price.cache_read is not None
            and price.input is not None
            and price.input > 0
            # 容 2%：厂商表里偶有命中价与输入价几乎相等的写法（如 ~ 路由别名），
            # 真把命中/未命中两档读反会是数量级偏差，不会被这个容差放过
            and price.cache_read > price.input * 1.02
        ):
            upside.append(f"{price.key}({price.cache_read * 1e6:.4f} vs {price.input * 1e6:.4f})")
    _check(not bad_high, f"疑似单位没换算（每 1M 价高得离谱）: {bad_high[:5]}")
    _check(not bad_low, f"量级异常（每 1M 价过低或含负数哨兵值）: {bad_low[:5]}")
    _check(not upside, f"缓存命中价明显高于未命中价，口径可疑: {upside[:5]}")
    print(f"[OK] 单位量级：{len(catalog.prices)} 条价目全部落在合理区间")


def verify_channels(catalog) -> None:
    """同一模型的直连与网关渠道必须各自成条、价格可以不同。"""
    direct = catalog.get("deepseek-v4-flash")
    gateway = catalog.get("deepseek/deepseek-v4-flash")
    _check(direct is not None and gateway is not None, "两条渠道都应存在于价目表")
    if direct.cache_read is not None and gateway.cache_read is not None:
        _check(
            direct.cache_read != gateway.cache_read,
            "直连与网关的命中价被归一成同一条了，渠道区分失效",
        )
        print(
            f"[OK] 渠道区分：直连命中 {direct.cache_read * 1e6:.3f}/1M，"
            f"网关命中 {gateway.cache_read * 1e6:.3f}/1M"
        )
    else:
        print("[OK] 渠道区分：两条渠道各自成条")


def verify_costing(catalog) -> None:
    """真实日志计价：覆盖率、分段一致、无价为 None、单位量级。"""
    from core.llm.token_stats import build_overview

    data = build_overview(granularity="month", use_cache=False, catalog=catalog)
    cost = data.get("cost") or {}
    totals, cover, pricing = cost.get("totals"), cost.get("coverage"), cost.get("pricing")
    _check(bool(totals), "报表应带成本块")
    _check(totals["total"] is not None, "有价目表时成本合计不应为 None")
    _check(pricing["entry_count"] == len(catalog.prices), "报表里的价目表条目数应与目录一致")

    ratio = cover["priced_ratio"] or 0.0
    _check(ratio >= 0.8, f"计价覆盖率过低（{ratio:.1%}），厂商可能改名或价格页改版")

    segments = sum(totals[key] for key in ("input", "cache_read", "cache_write", "output"))
    _check(
        _approx(segments, totals["total"], 1e-5),
        f"分段之和不等于合计：{segments} vs {totals['total']}",
    )
    _check(
        _approx(data["totals"]["cost_total"], totals["total"], 1e-5),
        "桶级成本合计应与逐条汇总一致",
    )
    _check(
        sum(row["requests"] for row in data["by_channel"]) == data["totals"]["requests"],
        "按渠道的请求数之和应等于总请求数",
    )
    _check(
        sum(row["cost_priced"] for row in data["by_model"]) == cover["priced_requests"],
        "按模型的计价请求数之和应等于总计价请求数",
    )

    unpriced_buckets = [row for row in data["by_model"] if row["cost_priced"] == 0]
    _check(
        all(row["cost_total"] is None for row in unpriced_buckets),
        "一条价都没取到的桶必须显示无价，不能是 0",
    )
    _check(
        all(row["cost_total"] is None or row["cost_total"] >= 0 for row in data["by_model"]),
        "不应出现负成本",
    )

    average = totals["total"] / cover["priced_requests"]
    _check(
        1e-5 <= average <= 5.0,
        f"平均每请求成本 {average:.8f} 超出合理区间，怀疑单价单位出错",
    )
    _check(cover["peak_requests"] > 0, "真实日志跨峰时段，峰时请求数不应为 0")

    top = sorted(
        (row for row in data["by_model"] if row["cost_total"]),
        key=lambda row: row["cost_total"],
        reverse=True,
    )[:3]
    print(
        f"[OK] 计价：{cover['priced_requests']}/{cover['requests']} 次（{ratio:.1%}）"
        f"共 {totals['currency']} {totals['total']:.4f}，"
        f"峰时 {cover['peak_requests']} 次，无价 tokens {cover['unpriced_tokens']:,}"
    )
    print("     Top 消费：" + "，".join(f"{row['key']} {row['cost_total']:.4f}" for row in top))
    if cost.get("unpriced"):
        print("     待补价：" + "，".join(item["model"] for item in cost["unpriced"][:5]))


def main() -> int:
    print("=" * 62)
    print("模型价目表同步与成本计算验证")
    print("=" * 62)
    try:
        catalog = verify_sync()
        verify_units(catalog)
        verify_channels(catalog)
        verify_costing(catalog)
    except AssertionError as exc:
        print(f"[FAIL] {exc}")
        return 1
    print("=" * 62)
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
