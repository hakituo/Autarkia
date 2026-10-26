"""真实标注集 A/B/C 报告：Wilson 区间 + 同题配对的精确 McNemar 检验。

报告只含题号、类型与统计量，不含对话正文；写在 output/evaluation/（不入库）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ARMS = ("A", "B", "C")
TYPE_LABELS = {
    "stable_fact": "稳定事实",
    "preference": "偏好",
    "knowledge_update": "知识更新",
    "temporal": "时间推理",
    "multi_turn": "多轮",
    "refusal": "应拒答",
}


def mcnemar_exact(
    rows_x: list[Mapping[str, Any]], rows_y: list[Mapping[str, Any]]
) -> dict[str, Any]:
    """同一批题上 x 对、y 错记 b；x 错、y 对记 c；双侧精确二项检验。"""
    passed_y = {row["query_id"]: bool(row.get("passed")) for row in rows_y}
    b = sum(1 for row in rows_x if row.get("passed") and not passed_y.get(row["query_id"]))
    c = sum(1 for row in rows_x if not row.get("passed") and passed_y.get(row["query_id"]))
    n = b + c
    if n == 0:
        return {"x_only": b, "y_only": c, "p_value": 1.0}
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n
    return {"x_only": b, "y_only": c, "p_value": round(min(1.0, 2 * tail), 4)}


def _rate(bundle: Mapping[str, Any]) -> str:
    if not bundle or not bundle.get("denominator"):
        return "—"
    ci = bundle.get("ci95") or [0, 0]
    return f"{bundle['passed']}/{bundle['denominator']}（{ci[0]:.2f}–{ci[1]:.2f}）"


def _extraction_lines(result: Mapping[str, Any]) -> list[str]:
    lines = [
        "| 臂 | 产物数 | 金标覆盖 | 来源可解析 | 解析失败率 | 新调用 / 缓存 | prompt+completion tokens |",
        "|---|---|---|---|---|---|---|",
    ]
    for arm in ARMS:
        ext = result["extraction"][arm]
        cov = ext["gold_coverage"]
        usage = ext["usage"]
        tokens = (
            usage.get("prompt_tokens", 0)
            + usage.get("cached_prompt_tokens", 0)
            + usage.get("completion_tokens", 0)
            + usage.get("cached_completion_tokens", 0)
        )
        lines.append(
            f"| {arm} | {ext['notes']} | {cov['matched']}/{cov['denominator']} | "
            f"{ext['provenance']['rate']} | {ext['parse_failure_rate']} | "
            f"{usage.get('calls', 0)} / {usage.get('cached_calls', 0)} | {tokens:,} |"
        )
    return lines


def _answer_lines(result: Mapping[str, Any]) -> list[str]:
    types = sorted({row["type"] for arm in ARMS for row in result["arms"][arm]["rows"]})
    header = "| 指标 | " + " | ".join(ARMS) + " |"
    lines = [header, "|---|" + "---|" * len(ARMS)]
    lines.append(
        "| **端到端正确率（95% Wilson）** | "
        + " | ".join(_rate(result["arms"][arm]["answers"]["overall"]) for arm in ARMS)
        + " |"
    )
    for qtype in types:
        lines.append(
            f"| {TYPE_LABELS.get(qtype, qtype)} | "
            + " | ".join(
                _rate(result["arms"][arm]["answers"]["by_type"].get(qtype, {})) for arm in ARMS
            )
            + " |"
        )
    k = result["k"]
    for metric, label in (("recall", f"Recall@{k}"), ("ndcg", f"nDCG@{k}")):
        cells = []
        for arm in ARMS:
            bundle = result["arms"][arm]["retrieval"][metric]
            ci = bundle.get("ci95") or [0, 0]
            cells.append(f"{bundle['mean']}（{ci[0]:.2f}–{ci[1]:.2f}，n={bundle['n']}）")
        lines.append(f"| {label}（bootstrap） | " + " | ".join(cells) + " |")
    lines.append(
        "| 检索文档数 | "
        + " | ".join(str(result["arms"][arm]["corpus_docs"]) for arm in ARMS)
        + " |"
    )
    return lines


def _pair_lines(result: Mapping[str, Any]) -> list[str]:
    lines = ["| 对比 | 仅前者对 | 仅后者对 | 精确 McNemar p |", "|---|---|---|---|"]
    for x, y in (("C", "A"), ("C", "B"), ("B", "A")):
        test = mcnemar_exact(result["arms"][x]["rows"], result["arms"][y]["rows"])
        lines.append(f"| {x} vs {y} | {test['x_only']} | {test['y_only']} | {test['p_value']} |")
    return lines


def _matrix_lines(result: Mapping[str, Any]) -> list[str]:
    lines = ["| 题号 | 类型 | " + " | ".join(ARMS) + " |", "|---|---|" + "---|" * len(ARMS)]
    by_arm = {arm: {row["query_id"]: row for row in result["arms"][arm]["rows"]} for arm in ARMS}
    for qid, row in by_arm["A"].items():
        marks = ["✓" if by_arm[arm][qid]["passed"] else "✗" for arm in ARMS]
        lines.append(
            f"| {qid} | {TYPE_LABELS.get(row['type'], row['type'])} | " + " | ".join(marks) + " |"
        )
    return lines


def _ablation_lines(result: Mapping[str, Any]) -> list[str]:
    labels = {"C_facts": "C 只用事实（去原文）", "B_raw": "B 梗概 + 原文"}
    lines = ["| 语料 | 端到端 | Recall@k | 检索文档数 |", "|---|---|---|---|"]
    for arm, label in labels.items():
        data = result["arms"].get(arm)
        if not data:
            continue
        recall = data["retrieval"]["recall"]
        lines.append(
            f"| {label} | {_rate(data['answers']['overall'])} | {recall['mean']} | "
            f"{data['corpus_docs']} |"
        )
    for x, y in (("C_facts", "C"), ("B_raw", "B"), ("B", "C_facts")):
        if x in result["arms"] and y in result["arms"]:
            test = mcnemar_exact(result["arms"][x]["rows"], result["arms"][y]["rows"])
            lines.append(
                f"| {x} vs {y} | 仅前者对 {test['x_only']} / 仅后者对 "
                f"{test['y_only']} | p={test['p_value']} | |"
            )
    return lines


def _rejection_cell(count: Any) -> str:
    if isinstance(count, Mapping):
        return f"{count.get('deepseek', 0)}/{count.get('empty', 0)}"
    return f"0/{count}"


def write_real_report(result: Mapping[str, Any], path: Path) -> Path:
    seg = result["segmenter"]
    data_line = (
        f"- 数据：{result['dataset']}（{result.get('haystack')}），{result['queries']} 题；"
        f"主线 {result['turns']} 条消息、{result['segments']} 段（空闲 "
        f"{seg['idle_seconds'] // 60} 分钟 / {seg['max_turns']} 条 / {seg['max_chars']} 字封口）"
    )
    model_line = (
        f"- 模型：{result['provider']} / {result['model']}，temperature={result['temperature']}，"
        f"输出预算 {result['budgets']}，检索 {result.get('retriever', 'bm25')} top-{result['k']}"
    )
    lines = [
        "# 真实标注集 A/B/C 对照",
        "",
        data_line,
        model_line,
        "- 判分：关键词（命中任一答案词且不含禁用词；拒答题看拒答标记）",
        "",
        "## 端到端与检索",
        "",
        *_answer_lines(result),
        "",
        "## 配对检验（同 44 题）",
        "",
        *_pair_lines(result),
        "",
        "## 消融（不新增提取，只换检索语料）",
        "",
        *_ablation_lines(result),
        "",
        "## 提取",
        "",
        *_extraction_lines(result),
        "",
        "MiniMax 内容审核拒绝（HTTP 422）：改由 DeepSeek 补跑 / 补跑也失败记空产物 —— "
        + "，".join(
            f"{stage} {_rejection_cell(count)}"
            for stage, count in (result.get("rejected") or {}).items()
        ),
        "",
        "## 逐题",
        "",
        *_matrix_lines(result),
        "",
    ]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


__all__ = ["mcnemar_exact", "write_real_report"]
