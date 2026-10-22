#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""量化「资料段夹在 system 和历史之间」的缓存代价（只读分析）。

数据来源是 `logs/prompt_cache_prefix.log`（`record_prefix_layout` 写入）：
每条记录带当时的分段长度、必损块数 `ws_break_blocks` 和资料段指纹 `ws_fp`。

本脚本只回答三个问题：
1. 同一角色会话里，资料段实际多久变一次（`ws_fp` 变了就是一次断裂）；
2. 每断裂一次，白算多少块 / 多少 token；
3. 如果把资料段挪到历史之后，理论上能省下多少。

判定口径：
- 「断裂」= 同 key 相邻两条记录 `ws_fp` 不同，或 `history_count` 下降（历史被裁）；
- 损失只统计断裂那一条的 `ws_break_blocks`，因为上一次算的内容本可以复用；
- 块粒度 128 tokens，与线上实测一致（hit_tokens 99.3% 为 128 的整数倍）。

用法（项目根目录）：
    venv_cpu\\Scripts\\python.exe tests\\scripts\\prompt_cache\\analyze_prefix_break.py
    venv_cpu\\Scripts\\python.exe tests\\scripts\\prompt_cache\\analyze_prefix_break.py --days 7
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOG_PATH = PROJECT_ROOT / "logs" / "prompt_cache_prefix.log"


def load_records(days: int = 0) -> List[Dict[str, Any]]:
    """读 JSONL 并按时间排序；days>0 时只保留最近 N 天。"""
    if not LOG_PATH.exists():
        raise SystemExit(f"缺少日志: {LOG_PATH}（先跑一轮真实对话生成埋点）")

    cutoff = None
    if days > 0:
        cutoff = datetime.now().astimezone() - timedelta(days=days)

    rows: List[Dict[str, Any]] = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            when = datetime.fromisoformat(str(row["timestamp"]))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        if cutoff is not None and when < cutoff:
            continue
        row["_when"] = when
        rows.append(row)

    rows.sort(key=lambda item: item["_when"])
    return rows


def pct(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * q))
    return ordered[index]


def analyze(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        raise SystemExit("没有可分析样本")

    by_key: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_key[str(row.get("key") or "unknown")].append(row)

    total_breaks = 0
    total_loss_blocks = 0
    total_loss_tokens = 0
    break_loss_blocks: List[int] = []
    span_minutes: List[float] = []
    per_key: List[Dict[str, Any]] = []

    for key, items in by_key.items():
        items.sort(key=lambda item: item["_when"])
        breaks = 0
        loss_blocks = 0
        loss_tokens = 0
        key_break_losses: List[int] = []

        for prev, cur in zip(items, items[1:]):
            gap = (cur["_when"] - prev["_when"]).total_seconds() / 60
            span_minutes.append(gap)

            ws_changed = prev.get("ws_fp") != cur.get("ws_fp")
            history_shrank = int(cur.get("history_count") or 0) < int(
                prev.get("history_count") or 0
            )
            if not ws_changed and not history_shrank:
                continue

            breaks += 1
            blocks = int(cur.get("ws_break_blocks") or 0)
            tokens = int(cur.get("ws_break_tokens") or 0)
            loss_blocks += blocks
            loss_tokens += tokens
            break_loss_blocks.append(blocks)
            key_break_losses.append(blocks)

        total_breaks += breaks
        total_loss_blocks += loss_blocks
        total_loss_tokens += loss_tokens
        per_key.append(
            {
                "key": key,
                "samples": len(items),
                "breaks": breaks,
                "loss_blocks": loss_blocks,
                "loss_tokens": loss_tokens,
                "reusable_blocks": int(items[-1].get("reusable_blocks") or 0),
                "avg_break_blocks": int(statistics.fmean(key_break_losses))
                if key_break_losses
                else 0,
            }
        )

    transitions = max(0, len(rows) - len(by_key))
    break_rate = total_breaks / transitions if transitions else 0.0

    print(f"▶ 样本 {len(rows)} 条 / 会话 {len(by_key)} 个 / 相邻对比 {transitions} 次")
    print()
    print("[1] 资料段断裂频率")
    print(f"  断裂 {total_breaks} 次，断裂率 {break_rate * 100:.1f}%")
    if span_minutes:
        print(
            f"  同会话相邻请求间隔  中位 {pct(span_minutes, 0.5):.1f} 分钟"
            f"  p90 {pct(span_minutes, 0.9):.1f} 分钟"
        )
    print()

    print("[2] 每次断裂的代价（128 token / 块）")
    if break_loss_blocks:
        print(
            f"  白算块数  中位 {pct(break_loss_blocks, 0.5):.0f}"
            f"  p90 {pct(break_loss_blocks, 0.9):.0f}"
            f"  最大 {max(break_loss_blocks)}"
        )
        print(f"  累计白算 {total_loss_blocks} 块 ≈ {total_loss_tokens} tokens")
    else:
        print("  没有观测到断裂")
    print()

    print("[3] 按会话排行（白算块数前 8）")
    per_key.sort(key=lambda item: item["loss_blocks"], reverse=True)
    print(f"  {'会话':<28}{'样本':>6}{'断裂':>6}{'白算块':>8}{'白算tok':>10}{'system可复用块':>14}")
    for item in per_key[:8]:
        print(
            f"  {item['key'][:28]:<28}{item['samples']:>6}{item['breaks']:>6}"
            f"{item['loss_blocks']:>8}{item['loss_tokens']:>10}"
            f"{item['reusable_blocks']:>14}"
        )
    print()

    print("[4] 上界估算")
    if total_loss_tokens:
        saved_tokens = total_loss_tokens
        print(f"  资料段挪到历史之后，同样对话量可少算 ≈ {saved_tokens} tokens")
    else:
        print("  无损失，资料段在观测期内保持稳定")
    print()
    print("结果: 分析完成（只读）")


def main() -> int:
    parser = argparse.ArgumentParser(description="前缀断裂损失分析（只读）")
    parser.add_argument("--days", type=int, default=0, help="只看最近 N 天，0 表示全部")
    args = parser.parse_args()

    analyze(load_records(days=args.days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
