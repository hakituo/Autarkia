#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM token 用量汇总（命令行）。

读取 ``logs/prompt_cache_stats.log``，按日 / 月、模型、provider、调用来源
汇总输入 / 缓存命中 / 缓存未命中 / 输出 token。默认纯本地只读；
带 ``--pricing`` 时按价目表现算成本（价目表缺失会联网抓取一次）。

用法：
    venv_cpu\\Scripts\\python.exe scripts\\tools\\token_stats.py
    venv_cpu\\Scripts\\python.exe scripts\\tools\\token_stats.py --granularity day
    venv_cpu\\Scripts\\python.exe scripts\\tools\\token_stats.py --model deepseek-v4-flash
    venv_cpu\\Scripts\\python.exe scripts\\tools\\token_stats.py --pricing
    venv_cpu\\Scripts\\python.exe scripts\\tools\\token_stats.py --sync-pricing
    venv_cpu\\Scripts\\python.exe scripts\\tools\\token_stats.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def _fmt_int(value: Any) -> str:
    return f"{int(value or 0):,}"


def _fmt_rate(value: Any) -> str:
    return "-" if value is None else f"{float(value) * 100:.1f}%"


def _fmt_money(value: Any) -> str:
    """金额没有就写「无价」，不能写成 0——0 会被读成没花钱。"""
    return "无价" if value is None else f"{float(value):.4f}"


def _bucket_row(label: str, bucket: Dict[str, Any], with_cost: bool) -> List[str]:
    row = [
        label,
        _fmt_int(bucket.get("requests")),
        _fmt_int(bucket.get("prompt_tokens")),
        _fmt_rate(bucket.get("hit_rate")),
        _fmt_int(bucket.get("completion_tokens")),
        _fmt_int(bucket.get("total_tokens")),
    ]
    if with_cost:
        row.append(_fmt_money(bucket.get("cost_total")))
    return row


HEADERS = ["维度", "请求", "输入tokens", "缓存命中率", "输出tokens", "合计tokens"]


def _headers(with_cost: bool) -> List[str]:
    return HEADERS + (["成本"] if with_cost else [])


def render(data: Dict[str, Any], granularity: str, top: int) -> str:
    """把 overview 数据渲染成文本报表。"""
    coverage = data["coverage"]
    archive = data["archive"]
    totals = data["totals"]
    cost = data.get("cost")
    with_cost = bool(cost)
    headers = _headers(with_cost)
    lines: List[str] = []
    lines.append("=" * 78)
    lines.append("LLM token 用量统计")
    lines.append(f"数据源: {data['log_path']}")
    lines.append(
        f"归档范围: {archive['first_ts']} → {archive['last_ts']}"
        f"（{_fmt_int(archive['records'])} 条记录）"
    )
    if not coverage["records"]:
        lines.append("当前筛选条件下没有记录。")
        lines.append("=" * 78)
        return "\n".join(lines)

    lines.append(
        f"筛选结果: {_fmt_int(coverage['records'])} 次调用"
        f" | 有输出token记录: {_fmt_int(coverage['with_completion'])} 次"
        f" | 有缓存字段: {_fmt_int(coverage['with_cache'])} 次"
    )
    lines.append("-" * 78)
    lines.append(f"输入 tokens      : {_fmt_int(totals['prompt_tokens'])}")
    lines.append(f"  缓存命中        : {_fmt_int(totals['hit_tokens'])}")
    lines.append(f"  缓存未命中      : {_fmt_int(totals['miss_tokens'])}")
    lines.append(f"  综合命中率      : {_fmt_rate(totals['hit_rate'])}")
    lines.append(f"输出 tokens      : {_fmt_int(totals['completion_tokens'])}")
    lines.append(f"合计 tokens      : {_fmt_int(totals['total_tokens'])}")
    lines.append("")
    if cost:
        lines.extend(_cost_lines(cost))

    lines.append("[按模型]")
    rows = [_bucket_row(b["key"], b, with_cost) for b in data["by_model"][:top]]
    lines.append("\n".join(_table_text(rows, headers)))
    lines.append("")

    if with_cost:
        lines.append("[按采购渠道]")
        rows = [_bucket_row(b["key"], b, with_cost) for b in data.get("by_channel", [])[:top]]
        lines.append("\n".join(_table_text(rows, headers)))
        lines.append("")

    lines.append(f"[按{'月' if granularity == 'month' else '日'}]")
    rows = [_bucket_row(b["key"], b, with_cost) for b in data["series"]]
    lines.append("\n".join(_table_text(rows, headers)))
    lines.append("")

    lines.append("[按 provider]")
    rows = [_bucket_row(b["key"], b, with_cost) for b in data["by_provider"][:top]]
    lines.append("\n".join(_table_text(rows, headers)))
    lines.append("")

    lines.append("[按调用来源 Top]")
    rows = [_bucket_row(b["key"], b, with_cost) for b in data["by_source"][:top]]
    lines.append("\n".join(_table_text(rows, headers)))
    lines.append("=" * 78)
    return "\n".join(lines)


def _cost_lines(cost: Dict[str, Any]) -> List[str]:
    """成本段：金额构成 + 计价覆盖 + 价目表健康度 + 待补价清单。"""
    totals = cost["totals"]
    cover = cost["coverage"]
    pricing = cost["pricing"]
    currency = totals["currency"]
    lines = ["[成本]"]
    lines.append(f"合计金额         : {_fmt_money(totals['total'])} {currency}")
    lines.append(f"  输入（未命中）  : {_fmt_money(totals['input'])}")
    lines.append(f"  缓存命中读      : {_fmt_money(totals['cache_read'])}")
    lines.append(f"  缓存写入        : {_fmt_money(totals['cache_write'])}")
    lines.append(f"  输出            : {_fmt_money(totals['output'])}")
    lines.append(
        f"计价覆盖         : {_fmt_int(cover['priced_requests'])}/{_fmt_int(cover['requests'])}"
        f"（{_fmt_rate(cover['priced_ratio'])}）"
        f" | 无价 tokens {_fmt_int(cover['unpriced_tokens'])}"
        f" | 峰时请求 {_fmt_int(cover['peak_requests'])}"
    )
    sources = " ".join(
        f"{name}={'ok' if st.get('ok') else ('停用' if st.get('skipped') else '失败')}"
        for name, st in (pricing.get("sources") or {}).items()
    )
    lines.append(
        f"价目表           : {_fmt_int(pricing['entry_count'])} 条"
        f" | 同步于 {pricing['synced_at'] or '从未'}"
        f"{' | 已过期' if pricing['stale'] else ''}"
    )
    lines.append(f"  来源状态        : {sources or '（无）'}")
    if cost["unpriced"]:
        lines.append("[待补价模型]")
        for item in cost["unpriced"]:
            lines.append(
                f"  {item['model']:<28} 请求 {_fmt_int(item['requests']):>7}"
                f"  tokens {_fmt_int(item['prompt_tokens'] + item['completion_tokens']):>12}"
                f"  {item['reason']}"
            )
    lines.append("")
    return lines


def _table_text(rows: List[List[str]], headers: List[str]) -> List[str]:
    """定宽排版，返回行列表（便于拼进整体字符串）。"""
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    output = ["  ".join(headers[i].ljust(widths[i]) for i in range(len(headers)))]
    output.append("-" * len(output[0]))
    for row in rows:
        output.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
    return output


def _load_catalog(force_sync: bool):
    """按需取价目表：只有显式要求成本/同步时才联网。"""
    import asyncio

    from core.llm.token_stats.pricing import ensure_catalog

    return asyncio.run(ensure_catalog(force=force_sync))


def main() -> int:
    from core.llm.token_stats import build_overview

    parser = argparse.ArgumentParser(description="LLM token 用量汇总")
    parser.add_argument("--granularity", choices=("day", "month"), default="month")
    parser.add_argument("--start", default="", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default="", help="结束日期 YYYY-MM-DD")
    parser.add_argument("--model", default="", help="按模型精确筛选")
    parser.add_argument("--provider", default="", help="按 provider 精确筛选")
    parser.add_argument("--top", type=int, default=20, help="分布表取前 N 项")
    parser.add_argument("--log", default="", help="自定义日志路径（默认 logs/）")
    parser.add_argument("--pricing", action="store_true", help="按价目表计算并展示成本")
    parser.add_argument("--sync-pricing", action="store_true", help="强制重抓价目表后再统计")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    log_path = Path(args.log) if args.log else None
    catalog: Optional[Any] = None
    if args.pricing or args.sync_pricing:
        catalog = _load_catalog(args.sync_pricing)
    data = build_overview(
        granularity=args.granularity,
        start=args.start,
        end=args.end,
        model=args.model,
        provider=args.provider,
        top=args.top,
        log_path=log_path,
        catalog=catalog,
    )
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render(data, args.granularity, args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
