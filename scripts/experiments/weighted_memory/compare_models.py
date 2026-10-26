#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对比 MiniMax-M3.1-Flash 与 MiniMax-M3 在同一 C6/C7 条件下的质量、成本与延迟。

    venv_cpu\\Scripts\\python.exe scripts\\experiments\\weighted_memory\\compare_models.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.experiments.weighted_memory.report import _choose_arm  # noqa: E402

DEFAULT_DIR = ROOT_DIR / "output" / "evaluation"
ARMS = ("A", "B", "C")


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _tokens(c6: Dict[str, Any], arm: str) -> int:
    usage = ((c6.get("metrics") or {}).get(arm) or {}).get("usage") or {}
    return sum(
        int(usage.get(key) or 0)
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "cached_prompt_tokens",
            "cached_completion_tokens",
        )
    )


def _mean_latency(c6: Dict[str, Any], arm: str) -> Optional[float]:
    usage = ((c6.get("metrics") or {}).get(arm) or {}).get("usage") or {}
    calls = int(usage.get("calls") or 0)
    if not calls:
        return None
    return round(float(usage.get("wall_seconds") or 0) / calls, 2)


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _ratio(bundle: Optional[Dict[str, Any]]) -> str:
    if not bundle or bundle.get("rate") is None:
        return "—"
    return f"{bundle.get('passed')}/{bundle.get('denominator')} = {bundle.get('rate'):.2f}"


def _rows(label: str, c6: Dict[str, Any], c7: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    for arm in ARMS:
        metrics = (c6.get("metrics") or {}).get(arm) or {}
        coverage = (metrics.get("gold_coverage") or {}).get("rate")
        supported = (metrics.get("supported_notes") or {}).get("supported_rate")
        retrieval = ((c7.get("arms") or {}).get(arm) or {}).get("retrieval") or {}
        answers = ((c7.get("arms") or {}).get(arm) or {}).get("answers") or {}
        cross = ((c7.get("arms") or {}).get(arm) or {}).get("cross_line") or {}
        lines.append(
            f"| {label} | {arm} | {_fmt(coverage)} | {_fmt(supported)} | "
            f"{_fmt((retrieval.get('recall') or {}).get('mean'))} | "
            f"{_fmt((retrieval.get('ndcg') or {}).get('mean'))} | "
            f"{_ratio(answers.get('overall'))} | "
            f"{_ratio(answers.get('knowledge_update'))} | "
            f"{_ratio(answers.get('refusal'))} | "
            f"{cross.get('cross_line_evidence')} | {_tokens(c6, arm)} | "
            f"{_fmt(_mean_latency(c6, arm))} |"
        )
    return lines


def _recommend(flash: Dict[str, Any], m3: Dict[str, Any]) -> Dict[str, Any]:
    flash_arm = _choose_arm(flash["c6"], flash["c7"])["chosen"]
    m3_arm = _choose_arm(m3["c6"], m3["c7"])["chosen"]

    def _pick(pack: Dict[str, Any], arm: str) -> Dict[str, Any]:
        answers = ((pack["c7"].get("arms") or {}).get(arm) or {}).get("answers") or {}
        accuracy = (answers.get("overall") or {}).get("rate") or 0.0
        coverage = (
            ((pack["c6"].get("metrics") or {}).get(arm) or {}).get("gold_coverage") or {}
        ).get("rate") or 0.0
        return {
            "arm": arm,
            "accuracy": accuracy,
            "coverage": coverage,
            "tokens": _tokens(pack["c6"], arm),
            "latency": _mean_latency(pack["c6"], arm),
        }

    flash_best = _pick(flash, flash_arm)
    m3_best = _pick(m3, m3_arm)
    delta = round(m3_best["accuracy"] - flash_best["accuracy"], 4)
    token_ratio = (
        round(m3_best["tokens"] / flash_best["tokens"], 2)
        if flash_best["tokens"]
        else None
    )
    latency_ratio = (
        round(m3_best["latency"] / flash_best["latency"], 2)
        if m3_best["latency"] and flash_best["latency"]
        else None
    )
    if delta >= 0.10 and m3_best["coverage"] >= flash_best["coverage"]:
        choice = "MiniMax-M3"
        reason = "M3 在回答正确率上领先至少 2 个问题，且覆盖不低；可接受更高成本时优先 M3"
    else:
        choice = "MiniMax-M3.1-Flash"
        reason = "两模型在 20 个问题上的差异小于 2 个问题，落在小样本噪声内；Flash 成本/延迟更低，默认选 Flash"
    return {
        "flash": flash_best,
        "m3": m3_best,
        "delta_accuracy": delta,
        "token_ratio": token_ratio,
        "latency_ratio": latency_ratio,
        "choice": choice,
        "reason": reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="对比 Flash 与 M3 的 C6/C7 结果")
    parser.add_argument("--dir", default=str(DEFAULT_DIR))
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    base = Path(args.dir)
    flash = {
        "c6": _load(base / "c6_extraction_artifacts.json"),
        "c7": _load(base / "c7_retrieval_e2e.json"),
    }
    m3 = {
        "c6": _load(base / "c6_extraction_artifacts_m3.json"),
        "c7": _load(base / "c7_retrieval_e2e_m3.json"),
    }
    decision = _recommend(flash, m3)

    lines = [
        "# MiniMax-M3.1-Flash vs MiniMax-M3（C6/C7 同条件对比）",
        "",
        f"- Flash：`{flash['c7'].get('model')}`；M3：`{m3['c7'].get('model')}`",
        f"- 生成时间：Flash {flash['c7'].get('generated_at')} / M3 {m3['c7'].get('generated_at')}",
        "- 同一评测集、同一 prompt、temperature=0、同一检索 k 与评分规则；",
        "- M3 使用 `reasoning_split=True`，tokens 含推理 token；两份结果不混算置信区间。",
        "",
        "## 1. 明细",
        "",
        "| 模型 | 臂 | 金标覆盖 | 有据可依 | Recall@5 | nDCG@5 | 端到端 | 知识更新 | 拒答 | 跨线 | tokens | 平均延迟(s) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
        *_rows("Flash", flash["c6"], flash["c7"]),
        *_rows("M3", m3["c6"], m3["c7"]),
        "",
        "## 2. 各自最优臂",
        "",
        f"- Flash：臂 {decision['flash']['arm']}，回答正确率 {decision['flash']['accuracy']:.2f}，"
        f"金标覆盖 {decision['flash']['coverage']:.2f}，tokens {decision['flash']['tokens']}，"
        f"平均延迟 {decision['flash']['latency']}s；",
        f"- M3：臂 {decision['m3']['arm']}，回答正确率 {decision['m3']['accuracy']:.2f}，"
        f"金标覆盖 {decision['m3']['coverage']:.2f}，tokens {decision['m3']['tokens']}，"
        f"平均延迟 {decision['m3']['latency']}s；",
        f"- 正确率差（M3 - Flash）：{decision['delta_accuracy']:+.2f}；"
        f"token 倍数：{decision['token_ratio']}；延迟倍数：{decision['latency_ratio']}。",
        "",
        "## 3. 选型建议",
        "",
        f"- **{decision['choice']}**。{decision['reason']}。",
        "",
        "## 4. 限制",
        "",
        "- 10 个合成案例 / 20 个问题，任何小于 2 个问题的差异都不应视为稳定优势；",
        "- M3 的推理 token 计入成本，但未单独统计推理时长；",
        "- BM25 检索对“悬疑剧”这类未分词短语存在召回缺口，两模型同受影响；",
        "- 该对比只回答“同一离线原型下选哪个模型”，不替代真实数据上的生产验收。",
        "",
        "原始数据：`output/evaluation/`（不入库）。",
        "",
    ]
    out_path = Path(args.out) if args.out else base / "model_comparison.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[对比] {decision['choice']}；正确率差 {decision['delta_accuracy']:+.2f}")
    print(f"[报告] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
