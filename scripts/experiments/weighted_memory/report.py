"""把 C6/C7 结果装配成可读 Markdown：对照表、结论与限制。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

ARMS = ("A", "B", "C")
ARM_LABELS = {
    "A": "A 逐消息摘要（当前粒度）",
    "B": "B segment 单 episode",
    "C": "C raw turns + fact 扩展",
}


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _ci(bundle: Optional[Dict[str, Any]]) -> str:
    if not bundle:
        return "—"
    ci = bundle.get("ci95")
    mean = bundle.get("mean")
    if mean is None:
        return "—"
    if ci:
        return f"{_fmt(mean)} [{_fmt(ci[0])}, {_fmt(ci[1])}] n={bundle.get('n')}"
    return _fmt(mean)


def _ratio(bundle: Optional[Dict[str, Any]]) -> str:
    if not bundle:
        return "—"
    rate = bundle.get("rate")
    ci = bundle.get("ci95")
    if rate is None:
        return f"{bundle.get('passed')}/{bundle.get('denominator')}"
    if ci:
        return f"{bundle.get('passed')}/{bundle.get('denominator')} = {_fmt(rate)} [{_fmt(ci[0])}, {_fmt(ci[1])}]"
    return f"{bundle.get('passed')}/{bundle.get('denominator')} = {_fmt(rate)}"


def _choose_arm(c6: Dict[str, Any], c7: Dict[str, Any]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for arm in ARMS:
        metrics = (c6.get("metrics") or {}).get(arm) or {}
        arm_c7 = (c7.get("arms") or {}).get(arm) or {}
        provenance = (metrics.get("provenance") or {}).get("rate")
        parse_fail = metrics.get("parse_failure_rate")
        cross = (arm_c7.get("cross_line") or {}).get("cross_line_evidence")
        accuracy = ((arm_c7.get("answers") or {}).get("overall") or {}).get("rate")
        recall = ((arm_c7.get("retrieval") or {}).get("recall") or {}).get("mean")
        tokens = sum(
            int((c6.get("usage") or {}).get(arm, {}).get(key) or 0)
            for key in (
                "prompt_tokens",
                "completion_tokens",
                "cached_prompt_tokens",
                "cached_completion_tokens",
            )
        )
        hard_ok = (
            provenance == 1.0
            and (parse_fail in (0, 0.0, None))
            and (cross in (0, None))
        )
        rows.append(
            {
                "arm": arm,
                "hard_ok": hard_ok,
                "accuracy": accuracy if accuracy is not None else 0.0,
                "recall": recall if recall is not None else 0.0,
                "tokens": tokens,
            }
        )
    eligible = [row for row in rows if row["hard_ok"]]
    baseline = next(row for row in rows if row["arm"] == "A")
    if not eligible:
        return {
            "chosen": "A",
            "reason": "没有实验臂同时满足 provenance=100% / 解析零失败 / 跨线=0，保留 A",
            "eligible": [],
        }
    best = max(
        eligible,
        key=lambda row: (row["accuracy"], row["recall"], -row["tokens"]),
    )
    if best["arm"] != "A":
        if best["accuracy"] < baseline["accuracy"] or best["recall"] < baseline["recall"]:
            return {
                "chosen": "A",
                "reason": "候选臂在回答正确率或 Recall 上低于 A，按预注册规则保留 A",
                "eligible": [row["arm"] for row in eligible],
                "best": best["arm"],
            }
    return {
        "chosen": best["arm"],
        "reason": "同时满足硬约束，且回答正确率/Recall 不低于 A",
        "eligible": [row["arm"] for row in eligible],
    }


def _c6_table(c6: Dict[str, Any]) -> List[str]:
    lines = [
        "| 臂 | notes | 金标事实覆盖 | 有据可依笔记率 | provenance | 解析失败率 | tokens | 用时(s) | 平均延迟(s) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for arm in ARMS:
        metrics = (c6.get("metrics") or {}).get(arm) or {}
        coverage = metrics.get("gold_coverage") or {}
        supported = metrics.get("supported_notes") or {}
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
        calls = usage.get("calls") or 0
        mean_latency = (
            round((usage.get("wall_seconds") or 0) / calls, 2) if calls else None
        )
        coverage_text = (
            f"{coverage.get('matched')}/{coverage.get('denominator')} = "
            f"{_fmt(coverage.get('rate'))} CI={coverage.get('ci95')}"
        )
        lines.append(
            f"| {arm} | {metrics.get('notes')} | {coverage_text} | "
            f"{_fmt(supported.get('supported_rate'))} | "
            f"{_fmt((metrics.get('provenance') or {}).get('rate'))} | "
            f"{_fmt(metrics.get('parse_failure_rate'))} | {tokens} | "
            f"{_fmt(usage.get('wall_seconds'), 1)} | {_fmt(mean_latency, 2)} |"
        )
    return lines


def _c7_table(c7: Dict[str, Any]) -> List[str]:
    lines = [
        "| 臂 | Recall@k | nDCG@k | 端到端正确率 | 知识更新 | 拒答 | 跨线证据 | 无过滤跨线（消融） | 消融正确率 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for arm in ARMS:
        data = (c7.get("arms") or {}).get(arm) or {}
        retrieval = data.get("retrieval") or {}
        answers = data.get("answers") or {}
        cross = data.get("cross_line") or {}
        ablation = data.get("ablation_without_branch_filter") or {}
        ablation_cross = (ablation.get("cross_line") or {}).get("cross_line_evidence")
        ablation_acc = ((ablation.get("answers") or {}).get("overall") or {}).get("rate")
        lines.append(
            f"| {arm} | {_ci(retrieval.get('recall'))} | {_ci(retrieval.get('ndcg'))} | "
            f"{_ratio(answers.get('overall'))} | "
            f"{_ratio(answers.get('knowledge_update'))} | "
            f"{_ratio(answers.get('refusal'))} | "
            f"{cross.get('cross_line_evidence')} | {_fmt(ablation_cross, 0)} | "
            f"{_fmt(ablation_acc)} |"
        )
    return lines


def _query_count(c7: Dict[str, Any]) -> int:
    arms = c7.get("arms") or {}
    for arm in ARMS:
        rows = (arms.get(arm) or {}).get("rows") or []
        if rows:
            return len(rows)
    return 0


def write_report(
    c6: Dict[str, Any],
    c7: Dict[str, Any],
    path: Path,
) -> Path:
    meta = c6.get("meta") or {}
    decision = _choose_arm(c6, c7)
    lines = [
        "# weighted memory v3：C6/C7 离线实验报告",
        "",
        f"- 生成时间：{c7.get('generated_at')}",
        f"- 模型：`{c7.get('provider')}` / `{c7.get('model')}`，temperature={c7.get('temperature')}",
        f"- 评测集：`{c6.get('fixture')}`（{meta.get('case_count')} 案例 / "
        f"{meta.get('turn_count')} 消息 / {_query_count(c7)} 问题）",
        f"- segment_turns={meta.get('segment_turns')}，检索 k={c7.get('k')}",
        "",
        "## 1. 实验设计",
        "",
        "- A：逐消息摘要，对应现有“一段/一条”粒度；",
        "- B：同一 segment 只产一条 episode 摘要；",
        "- C：raw turns 保持可检索，segment 额外产原子 fact 作为扩展索引；",
        "- 控制：同一模型、temperature=0、同一 system prompt、同一输入证据与预算；",
        "- 检索统一使用 BM25 + jieba，三个臂只改索引文档形态；",
        "- 端到端回答只看检索片段，声称找不到时必须拒答；",
        "- 分支评测：兄弟分支文档存在于语料中，主运行过滤，消融运行不过滤。",
        "",
        "## 2. C6 提取对照",
        "",
        *_c6_table(c6),
        "",
        "“金标事实覆盖”要求关键词命中且来源轮次与金标证据相交；“有据可依笔记率”是忠实度的"
        "自动代理（是否命中任一金标事实），不是人工评分。",
        "",
        "## 3. C7 检索与端到端",
        "",
        *_c7_table(c7),
        "",
        "按类型正确率：",
        "",
        "| 臂 | 类型 | 正确/总数 | 95% Wilson CI |",
        "|---|---|---|---|",
    ]
    for arm in ARMS:
        by_type = ((c7.get("arms") or {}).get(arm) or {}).get("answers", {}).get("by_type", {})
        for type_name, bundle in by_type.items():
            lines.append(f"| {arm} | {type_name} | {_ratio(bundle)} | — |")
    lines.extend(
        [
            "",
            "## 4. 结论（暂定，供 F3 拍板）",
            "",
            "- 预注册规则：先过硬约束（provenance=100%、解析零失败、过滤后跨线=0），"
            "再比端到端正确率与 Recall；候选不得低于 A。",
            f"- 本次选择：**{decision['chosen']}**（{ARM_LABELS.get(decision['chosen'])}）。",
            f"- 理由：{decision['reason']}。",
            f"- 满足硬约束的臂：{decision.get('eligible') or '无'}。",
            "",
            "## 5. 限制",
            "",
            "- 合成集只有 10 个案例 / 18 个问题，置信区间很宽；结论是原型信号，不是生产定论；",
            "- 忠实度用关键词代理，未做人工逐条标注；评分前对中文数字/日期做了确定性归一化"
            "（二百四十元 ↔ 240元、十月三号 ↔ 10月3日），避免格式差异被误判为错误；",
            "- 检索只用了 BM25，未覆盖 embedding / 混合检索；",
            "- segment_turns 固定为 fixture 值，生产参数仍需 C4 回放分布与更大规模 A/B；",
            "- 同一模型同时做提取、回答与规则判定，存在同源偏差；判定规则是确定性的，未用模型当裁判。",
            "",
            "原始数据：`output/evaluation/c6_extraction_artifacts.json`、"
            "`output/evaluation/c7_retrieval_e2e.json`（均不入库）。",
            "",
        ]
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


__all__ = ["write_report"]
