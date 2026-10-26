#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""C6：离线提取 A/B/C 对照，输出忠实度、证据覆盖、provenance、token 与延迟。

    venv_cpu\\Scripts\\python.exe scripts\\experiments\\weighted_memory\\run_c6.py --dry-run
    venv_cpu\\Scripts\\python.exe scripts\\experiments\\weighted_memory\\run_c6.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.utils.time.time_utils import now_iso  # noqa: E402
from scripts.experiments.weighted_memory.cases import (  # noqa: E402
    case_turns,
    gold_fact_map,
    load_cases,
    segment_case,
)
from scripts.experiments.weighted_memory.extraction import run_extraction  # noqa: E402
from scripts.experiments.weighted_memory.llm_client import (  # noqa: E402
    DEFAULT_PROVIDER,
    PROVIDERS,
    OpenAICompatClient,
)
from scripts.experiments.weighted_memory.metrics import arm_extraction_metrics  # noqa: E402

DEFAULT_OUT = ROOT_DIR / "output" / "evaluation" / "c6_extraction_artifacts.json"
DEFAULT_CACHE = ROOT_DIR / "output" / "evaluation" / "llm_cache.jsonl"


def _print_metrics(metrics: Dict[str, Any]) -> None:
    coverage = metrics.get("gold_coverage") or {}
    supported = metrics.get("supported_notes") or {}
    provenance = metrics.get("provenance") or {}
    usage = metrics.get("usage") or {}
    tokens = sum(
        int(usage.get(key) or 0)
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "cached_prompt_tokens",
            "cached_completion_tokens",
        )
    )
    live_calls = int(usage.get("calls") or 0)
    mean_latency = (
        round((usage.get("wall_seconds") or 0) / live_calls, 2) if live_calls else None
    )
    print(
        f"  notes={metrics.get('notes')} "
        f"gold_coverage={coverage.get('matched')}/{coverage.get('denominator')} "
        f"({coverage.get('rate')}, CI={coverage.get('ci95')}) "
        f"supported={supported.get('supported_rate')} "
        f"provenance={provenance.get('rate')} "
        f"parse_fail={metrics.get('parse_failure_rate')}"
    )
    print(
        f"  usage: live_calls={live_calls} cached={usage.get('cached_calls')} "
        f"tokens={tokens} wall={usage.get('wall_seconds')}s "
        f"mean_latency={mean_latency}s"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="C6 离线提取 A/B/C 对照")
    parser.add_argument("--cases", default="", help="评测集路径，默认 tests/fixtures")
    parser.add_argument("--segment-turns", type=int, default=0, help="覆盖 fixture 的 segment_turns")
    parser.add_argument("--limit-cases", type=int, default=0, help="只跑前 N 个案例（冒烟）")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--cache", default=str(DEFAULT_CACHE))
    parser.add_argument(
        "--provider",
        default=DEFAULT_PROVIDER,
        choices=sorted(PROVIDERS),
        help="模型供应商，默认 minimax-plan",
    )
    parser.add_argument("--model", default="", help="覆盖 provider 默认模型")
    parser.add_argument("--max-calls", type=int, default=200)
    parser.add_argument("--max-tokens", type=int, default=1_500_000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    fixture = load_cases(Path(args.cases) if args.cases else None)
    cases: List[Dict[str, Any]] = list(fixture.get("cases") or [])
    if args.limit_cases > 0:
        cases = cases[: args.limit_cases]
    segment_turns = args.segment_turns or int(fixture.get("segment_turns") or 4)

    turns = sum(len(case_turns(case)) for case in cases)
    segments = sum(len(segment_case(case, segment_turns)) for case in cases)
    if args.dry_run:
        print(f"[dry-run] cases={len(cases)} turns={turns} segments={segments}")
        print(f"[dry-run] 预计提取调用：A={turns} B={segments} C={segments}")
        return 0

    client = OpenAICompatClient(
        cache_path=Path(args.cache),
        provider=args.provider,
        model=args.model,
        max_calls=args.max_calls,
        max_total_tokens=args.max_tokens,
    )
    artifacts = run_extraction(cases, client, segment_turns=segment_turns)
    gold_by_case = {
        str(case.get("id")): gold_fact_map(case) for case in cases
    }
    artifacts["metrics"] = {
        arm: arm_extraction_metrics(
            artifacts["arms"].get(arm) or [],
            gold_by_case,
            artifacts["usage"].get(arm) or {},
        )
        for arm in ("A", "B", "C")
    }
    artifacts["generated_at"] = now_iso()
    artifacts["fixture"] = str(Path(args.cases) if args.cases else "tests/fixtures/memory_topology/extraction_e2e_cases.json")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(artifacts, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        f"[C6] {artifacts['generated_at']} provider={client.provider} "
        f"model={client.model} temperature={client.temperature}"
    )
    for arm in ("A", "B", "C"):
        print(f"[{arm}]")
        _print_metrics(artifacts["metrics"][arm])
    print(f"[汇总] client_usage={client.usage()}")
    print(f"[报告] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
