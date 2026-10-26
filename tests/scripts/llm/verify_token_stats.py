#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 token 用量统计：真实日志 + 合成记录两条链路。

真实日志验证（logs/prompt_cache_stats.log）：
1. 记录数、按月请求数、模型分布三处口径互相自洽；
2. 缓存命中率 = hit/(hit+miss)，且 hit 不超过 prompt；
3. 归档第一条记录时间早于最后一条。

合成记录验证（临时目录，不污染真实日志）：
4. 带 completion_tokens 的记录能进「输出 tokens」并按日 / 月分桶；
5. 历史记录（无 completion）不会被算成 0 输出而拉低命中率。

运行：
    venv_cpu\\Scripts\\python.exe tests\\scripts\\llm\\verify_token_stats.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.llm.token_stats import build_overview  # noqa: E402


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def verify_real_log() -> None:
    """真实日志三处口径自洽。"""
    from core.llm.token_stats import get_stats_log_path

    log_path = get_stats_log_path()
    _check(log_path.exists(), f"缺少日志: {log_path}")

    data = build_overview(granularity="month")
    totals = data["totals"]
    series = data["series"]
    by_model = data["by_model"]

    _check(totals["requests"] > 0, "真实日志应至少有一条记录")
    _check(
        sum(bucket["requests"] for bucket in series) == totals["requests"],
        "按月请求数之和应等于总请求数",
    )
    _check(
        sum(row["requests"] for row in by_model) == totals["requests"],
        "按模型请求数之和应等于总请求数（含『其他』合并桶）",
    )
    _check(
        totals["prompt_tokens"] >= totals["hit_tokens"] + totals["miss_tokens"],
        "输入 tokens 不应小于缓存命中 + 未命中",
    )
    if totals["hit_rate"] is not None:
        expected = totals["hit_tokens"] / (totals["hit_tokens"] + totals["miss_tokens"])
        _check(abs(totals["hit_rate"] - expected) < 1e-4, "缓存命中率口径不一致")
    _check(
        data["archive"]["first_ts"] <= data["archive"]["last_ts"],
        "归档首条时间应早于最后一条",
    )

    print(
        f"[OK] 真实日志：{totals['requests']} 次调用，"
        f"输入 {totals['prompt_tokens']:,} tokens，"
        f"命中率 {totals['hit_rate'] and round(totals['hit_rate'] * 100, 1)}%，"
        f"输出 {totals['completion_tokens']:,} tokens"
        f"（覆盖 {data['coverage']['with_completion']} 次）"
    )


def verify_synthetic_completion() -> None:
    """合成新记录：completion / total 字段必须进入聚合。"""
    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "synthetic.log"
        records = [
            {
                "timestamp": "2026-10-22T10:00:00+08:00",
                "provider": "openai_compat",
                "model": "deepseek-v4-flash",
                "source": "verify::run",
                "hit_tokens": 700,
                "miss_tokens": 300,
                "prompt_tokens": 1000,
                "completion_tokens": 200,
                "total_tokens": 1200,
            },
            {
                "timestamp": "2026-10-23T10:00:00+08:00",
                "provider": "openai_compat",
                "model": "MiniMax-M3",
                "hit_tokens": 0,
                "miss_tokens": 500,
                "prompt_tokens": 500,
            },
        ]
        log_path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n",
            encoding="utf-8",
        )

        day = build_overview(granularity="day", log_path=log_path)
        totals = day["totals"]
        _check(totals["completion_tokens"] == 200, "输出 tokens 应只累计有记录的调用")
        _check(totals["total_tokens"] == 1700, "合计 tokens 应为 1000+200 与 500 之和")
        _check(day["coverage"]["with_completion"] == 1, "输出 token 覆盖率应为 1/2")
        _check(len(day["series"]) == 2, "两天的记录应产生两个日桶")

        month = build_overview(granularity="month", log_path=log_path)
        _check(
            [bucket["key"] for bucket in month["series"]] == ["2026-10"],
            "跨日记录应落在同一个月桶",
        )
        print("[OK] 合成记录：completion / total_tokens 正确按日、月聚合")


def main() -> int:
    print("=" * 62)
    print("token 用量统计验证")
    print("=" * 62)
    try:
        verify_real_log()
        verify_synthetic_completion()
    except AssertionError as exc:
        print(f"[FAIL] {exc}")
        return 1
    print("=" * 62)
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
