#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""C7：同一离线原型跑检索 + 端到端回答对照，并做分支过滤消融。

    venv_cpu\\Scripts\\python.exe scripts\\experiments\\weighted_memory\\run_c7.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.utils.time.time_utils import now_iso  # noqa: E402
from scripts.experiments.weighted_memory.cases import load_cases  # noqa: E402
from scripts.experiments.weighted_memory.llm_client import (  # noqa: E402
    DEFAULT_PROVIDER,
    PROVIDERS,
    OpenAICompatClient,
)
from scripts.experiments.weighted_memory.metrics import (  # noqa: E402
    answer_metrics,
    cross_line_stats,
    retrieval_metrics,
)
from scripts.experiments.weighted_memory.report import write_report  # noqa: E402
from scripts.experiments.weighted_memory.retrieval import (  # noqa: E402
    build_corpus,
    run_queries,
)

DEFAULT_ARTIFACTS = ROOT_DIR / "output" / "evaluation" / "c6_extraction_artifacts.json"
DEFAULT_OUT = ROOT_DIR / "output" / "evaluation" / "c7_retrieval_e2e.json"
DEFAULT_CACHE = ROOT_DIR / "output" / "evaluation" / "llm_cache.jsonl"
DEFAULT_REPORT = ROOT_DIR / "output" / "evaluation" / "c6_c7_report.md"


def _arm_result(rows: List[Dict[str, Any]], k: int) -> Dict[str, Any]:
    return {
        "retrieval": retrieval_metrics(rows, k),
        "answers": answer_metrics(rows),
        "cross_line": cross_line_stats(rows),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="C7 检索与端到端对照")
    parser.add_argument("--artifacts", default=str(DEFAULT_ARTIFACTS))
    parser.add_argument("--cases", default="")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--cache", default=str(DEFAULT_CACHE))
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument(
        "--provider",
        default=DEFAULT_PROVIDER,
        choices=sorted(PROVIDERS),
        help="模型供应商，默认 minimax-plan",
    )
    parser.add_argument("--model", default="", help="覆盖 provider 默认模型")
    parser.add_argument("--max-calls", type=int, default=400)
    parser.add_argument("--max-tokens", type=int, default=3_000_000)
    parser.add_argument("--no-ablation", action="store_true")
    args = parser.parse_args()

    artifacts_path = Path(args.artifacts)
    if not artifacts_path.exists():
        print(f"[错误] 找不到 C6 artifacts：{artifacts_path}，先跑 run_c6.py")
        return 2
    artifacts = json.loads(artifacts_path.read_text(encoding="utf-8"))
    fixture = load_cases(Path(args.cases) if args.cases else None)
    cases: List[Dict[str, Any]] = list(fixture.get("cases") or [])

    client = OpenAICompatClient(
        cache_path=Path(args.cache),
        provider=args.provider,
        model=args.model,
        max_calls=args.max_calls,
        max_total_tokens=args.max_tokens,
    )
    result: Dict[str, Any] = {
        "generated_at": now_iso(),
        "k": args.k,
        "provider": client.provider,
        "model": client.model,
        "temperature": client.temperature,
        "case_count": len(cases),
        "arms": {},
        "usage": {},
    }

    for arm in ("A", "B", "C"):
        corpus = build_corpus(artifacts, arm, cases)
        before = client.usage()
        started = time.time()
        rows = run_queries(cases, corpus, client, k=args.k, branch_filter=True)
        after = client.usage()
        result["arms"][arm] = _arm_result(rows, args.k)
        result["usage"][arm] = {
            "calls": after["calls"] - before["calls"],
            "prompt_tokens": after["prompt_tokens"] - before["prompt_tokens"],
            "completion_tokens": after["completion_tokens"] - before["completion_tokens"],
            "wall_seconds": round(time.time() - started, 2),
        }
        if not args.no_ablation:
            before = client.usage()
            started = time.time()
            rows_free = run_queries(cases, corpus, client, k=args.k, branch_filter=False)
            after = client.usage()
            result["arms"][arm]["ablation_without_branch_filter"] = _arm_result(
                rows_free, args.k
            )
            result["usage"][arm]["ablation_calls"] = after["calls"] - before["calls"]
            result["usage"][arm]["ablation_wall_seconds"] = round(
                time.time() - started, 2
            )

    result["client_usage"] = client.usage()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report_path = write_report(artifacts, result, Path(args.report))

    print(
        f"[C7] {result['generated_at']} provider={client.provider} "
        f"model={client.model} k={args.k}"
    )
    for arm, data in result["arms"].items():
        retrieval = data["retrieval"]
        answers = data["answers"]["overall"]
        cross = data["cross_line"]
        print(
            f"[{arm}] recall@k={retrieval['recall']['mean']} "
            f"nDCG@k={retrieval['ndcg']['mean']} "
            f"answer={answers['passed']}/{answers['denominator']} ({answers['rate']}) "
            f"cross_line={cross['cross_line_evidence']}"
        )
    print(f"[汇总] client_usage={client.usage()}")
    print(f"[报告] {out_path}")
    print(f"[可读报告] {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
