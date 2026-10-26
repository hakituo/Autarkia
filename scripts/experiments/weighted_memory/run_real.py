"""C6/C7 在真实标注集上重跑：A 逐条 / B 段 episode / C 原文 + 段原子事实。

    venv_cpu/bin/python scripts/experiments/weighted_memory/run_real.py

三臂共用 C6/C7 的提取、检索、判分代码；这里只换输入（real_cases）和分段。
真实对话体量大，先用线程池并发预热同一份 LLM 缓存，再按原顺序串行跑一遍
（全部命中缓存），所以结果与串行执行一致、可断点续跑。产物只写 output/evaluation/。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.experiments.weighted_memory import extraction
from scripts.experiments.weighted_memory.cases import gold_fact_map
from scripts.experiments.weighted_memory.metrics import (
    answer_metrics,
    arm_extraction_metrics,
    retrieval_metrics,
)
from scripts.experiments.weighted_memory.real_cases import (
    EVAL_DIR,
    IDLE_SECONDS,
    MAX_SEGMENT_CHARS,
    MAX_SEGMENT_TURNS,
    load_real_cases,
    segment_turns,
)
from scripts.experiments.weighted_memory.real_client import (
    ModerationTolerantClient,
    PrefetchIncomplete,
    prefetch,
)
from scripts.experiments.weighted_memory.real_report import write_real_report
from scripts.experiments.weighted_memory.retrieval import BM25Index, build_corpus, run_queries
from scripts.experiments.weighted_memory.retrieval.hybrid import HybridIndex

#: MiniMax Flash 是推理模型，思考 token 计入 max_tokens：第一次实跑按合成集口径（220/800/1500）
#: 时 C 有 179/237 次打满、169 次正文为空，结论无效。预算须给足思考余量。
BUDGETS = {"A": 1024, "B": 3072, "C": 4096, "answer": 1024}


def _extract(cases: list[dict[str, Any]], arm: str, client: Any) -> list[dict[str, Any]]:
    if arm == "A":
        notes = extraction.run_arm_a(cases, client, max_tokens=BUDGETS["A"])
    elif arm == "B":
        notes = extraction.run_arm_b(cases, client, segment_turns=0, max_tokens=BUDGETS["B"])
    else:
        notes = extraction.run_arm_c(cases, client, segment_turns=0, max_tokens=BUDGETS["C"])
    for index, note in enumerate(notes):
        note["note_id"] = f"{arm}-{note['case_id']}-{index}"
    return notes


def _corpora(artifacts: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    """三个主臂 + 两个消融：C 只留事实（去原文）、B 加原文（梗概与原文同库）。

    消融不新增提取调用，只换检索语料，用来拆开「产物质量」和「原文稀释」两个因素。
    """
    corpora = {arm: build_corpus(artifacts, arm, cases) for arm in ("A", "B", "C")}
    corpora["C_facts"] = build_corpus({"arms": {"Cf": artifacts["arms"]["C"]}}, "Cf", cases)
    raw_only = build_corpus({"arms": {"C": []}}, "C", cases)
    corpora["B_raw"] = {
        case_id: list(corpora["B"].get(case_id, [])) + list(raw_only.get(case_id, []))
        for case_id in raw_only
    }
    return corpora


def _index_factory(name: str) -> Callable[[Any], Any]:
    if name == "bm25":
        return BM25Index
    from memory.embedding_generator import get_embedding_generator

    generator = get_embedding_generator()
    memo: dict[str, Any] = {}

    def embed(texts: list[str]) -> list[Any]:
        missing = [text for text in dict.fromkeys(texts) if text not in memo]
        if missing:
            memo.update(zip(missing, generator.generate_embeddings_batch(missing)))
        return [memo[text] for text in texts]

    return lambda docs: HybridIndex(docs, embed)


def main() -> int:
    parser = argparse.ArgumentParser(description="真实标注集 A/B/C 对照")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--cache", default=str(EVAL_DIR / "llm_cache_real.jsonl"))
    parser.add_argument("--out", default=str(EVAL_DIR / "real_abc_results.json"))
    parser.add_argument("--report", default=str(EVAL_DIR / "real_abc_report.md"))
    parser.add_argument("--max-calls", type=int, default=30_000)
    parser.add_argument("--max-tokens", type=int, default=40_000_000)
    parser.add_argument("--full", action="store_true", help="用整条主线，不做证据窗口抽样")
    parser.add_argument(
        "--deepseek-for-missing",
        action="store_true",
        help="主供应商额度用完时用：缓存里没有的请求直接交给 DeepSeek（报告里单独计数）",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="单次请求超时；C 臂每段要生成约 2000 token，45 秒会反复超时",
    )
    parser.add_argument(
        "--retriever",
        choices=("bm25", "hybrid"),
        default="bm25",
        help="hybrid = BM25 + bge-small-zh 向量 RRF 融合（提取结果走同一缓存，只多回答调用）",
    )
    args = parser.parse_args()

    # 分段换成真实分段（空闲 / 轮数 / 字数），其余提取逻辑与合成集一致
    extraction.segment_case = segment_turns
    fixture = load_real_cases(full=args.full)
    cases = fixture["cases"]
    client = ModerationTolerantClient(
        rejected_path=EVAL_DIR / "llm_rejected_real.txt",
        cache_path=Path(args.cache),
        max_calls=args.max_calls,
        max_total_tokens=args.max_tokens,
        timeout=args.timeout,
    )
    client.deepseek_for_missing = args.deepseek_for_missing
    result: dict[str, Any] = {
        "dataset": fixture["version"],
        "haystack": "full" if args.full else "evidence±15 + 同量随机干扰窗口",
        "provider": client.provider,
        "model": client.model,
        "temperature": client.temperature,
        "k": args.k,
        "budgets": BUDGETS,
        "segmenter": {
            "idle_seconds": IDLE_SECONDS,
            "max_turns": MAX_SEGMENT_TURNS,
            "max_chars": MAX_SEGMENT_CHARS,
        },
        "turns": sum(len(case["turns"]) for case in cases),
        "segments": sum(len(segment_turns(case)) for case in cases),
        "queries": sum(len(case["queries"]) for case in cases),
        "prefetch": {},
        "rejected": {},
        "extraction": {},
        "arms": {},
    }
    gold = {case["id"]: gold_fact_map(case) for case in cases}
    artifacts: dict[str, Any] = {"arms": {}}
    for arm in ("A", "B", "C"):
        result["prefetch"][f"extract_{arm}"] = prefetch(
            client, lambda c, a=arm: _extract(cases, a, c), args.workers, f"提取 {arm}"
        )
        before = client.usage()
        rejected_before, fallback_before = client.rejections, client.fallbacks
        notes = _extract(cases, arm, client)
        result["rejected"][f"extract_{arm}"] = {
            "empty": client.rejections - rejected_before,
            "deepseek": client.fallbacks - fallback_before,
        }
        after = client.usage()
        usage = {
            key: after[key] - before[key]
            for key in (
                "calls",
                "cached_calls",
                "prompt_tokens",
                "completion_tokens",
                "cached_prompt_tokens",
                "cached_completion_tokens",
            )
        }
        artifacts["arms"][arm] = notes
        result["extraction"][arm] = arm_extraction_metrics(notes, gold, usage)

    factory = _index_factory(args.retriever)
    result["retriever"] = args.retriever
    for arm, corpus in _corpora(artifacts, cases).items():
        result["prefetch"][f"answer_{arm}"] = prefetch(
            client,
            lambda c, cp=corpus: run_queries(
                cases, cp, c, k=args.k, max_tokens=BUDGETS["answer"], index_factory=factory
            ),
            args.workers,
            f"回答 {arm}",
        )
        rejected_before, fallback_before = client.rejections, client.fallbacks
        rows = run_queries(
            cases, corpus, client, k=args.k, max_tokens=BUDGETS["answer"], index_factory=factory
        )
        result["rejected"][f"answer_{arm}"] = {
            "empty": client.rejections - rejected_before,
            "deepseek": client.fallbacks - fallback_before,
        }
        result["arms"][arm] = {
            "corpus_docs": sum(len(v) for v in corpus.values()),
            "retrieval": retrieval_metrics(rows, args.k),
            "answers": answer_metrics(rows),
            "rows": rows,
        }

    result["client_usage"] = client.usage()
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (EVAL_DIR / "real_abc_notes.json").write_text(
        json.dumps(artifacts, ensure_ascii=False), encoding="utf-8"
    )
    report = write_real_report(result, Path(args.report))
    for arm, data in result["arms"].items():
        overall = data["answers"]["overall"]
        print(
            f"[{arm}] answer={overall['passed']}/{overall['denominator']} ci95={overall['ci95']} "
            f"recall@{args.k}={data['retrieval']['recall']['mean']}"
        )
    print(f"[报告] {report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PrefetchIncomplete as exc:
        print(f"[中止] {exc}")
        raise SystemExit(3)
