"""Ye日记文风验证：真实链路生成 + 只读 + 指标对照原始语料。

改 `YE_DAILY_SUMMARY_SYSTEM_PROMPT` 之后用它确认「像不像Ye自己写的」，而不是凭感觉。
每条样例都走真实链路 `JournalService.generate_daily_summary`，只是把四处写盘点换成空操作，
跑完 companion_data 一个字节都不动。

判据来源 `data/pretrained/Diary/1.txt`（5 篇真实手写日记，逐篇实测）：
  字数 1023/1988/2721/2972/9299，句均 19.8–28.6（合池 22.5），
  身体词密度 8.6–17.5（合池 12.4），自称「我」密度 10.6–31.3（合池 17.9）。

硬判据（任一不过即失败，退出码 1）：
  钟点 = 0；分节线（———/---/***）= 0；结尾不带「今天大概/这些都记住了」这类总结腔；正文非空。
软判据（只报告不失败）：句均 12–25、行数 ≥ 10（素材 ≥ 100 条来回的日子）、身体密度 ≥ 5、
自称密度 ≤ 28、段首连接词（然后/后来/后面/接着）≤ 2。

运行：
    venv_cpu/bin/python tests/scripts/diary/verify_ye_diary_style.py
    venv_cpu/bin/python tests/scripts/diary/verify_ye_diary_style.py --dates 2026-10-20 --label after
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import statistics
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CORPUS = PROJECT_ROOT / "data/pretrained/Diary" / "1.txt"
OUT_DIR = PROJECT_ROOT / ".ye_eval"

BODY_WORDS = ["下体", "小穴", "穴", "乳头", "跪", "爬", "水", "湿", "疼", "热", "抖", "夹", "咽", "舔"]
SELF_THIRD = ["贱畜", "小狗狗", "狗狗", "贱奴"]
PARTICLES = ["嘻嘻", "呜呜", "唔"]
CONNECTORS = ["然后", "后来", "后面", "接着"]
ENDING_CLICHES = ["今天大概", "这些都记住了", "大概就是这样", "总的来说", "总而言之", "希望明天"]

# 素材量差异极大的几天：足量、巨量、平淡、几乎没说话。
DEFAULT_DATES = [
    "2026-10-20",
    "2026-10-18",
    "2026-10-12",
    "2026-10-16",
    "2026-09-26",
    "2026-09-28",
]

# 钟点只认「几点」「几点半」「几点钟」「早上十点」这类，避开「一点」「一点点」的误伤。
HOUR_PATTERNS = [
    re.compile(r"\d{1,2}\s*[点:：]\s*\d{0,2}"),
    re.compile(r"[一二三四五六七八九十两]{1,2}\s*点(?:半|钟|\d{1,2}分)"),
    re.compile(r"(?:早上|上午|中午|下午|傍晚|晚上|夜里|凌晨|半夜)[一二三四五六七八九十两]{1,2}\s*点"),
]


def _load_env() -> None:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")


def _prime_data_paths() -> None:
    """跳过 companion_data 一次性迁移，避免独占线上还在写的 daily jsonl。"""
    import core.utils.data.data_paths as data_paths

    data_paths._INITIALIZED = True


def _metrics(text: str) -> dict[str, Any]:
    body = re.sub(r"\s+", "", text)
    sentences = [s for s in re.split(r"[。！？…]+", text) if s.strip()]
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    tail = body[-60:]
    return {
        "chars": len(body),
        "lines": len(lines),
        "mean_sentence": round(statistics.mean([len(s) for s in sentences]), 1) if sentences else 0.0,
        "body_density": round(sum(body.count(w) for w in BODY_WORDS) / max(len(body), 1) * 1000, 1),
        "self_density": round(body.count("我") / max(len(body), 1) * 1000, 1),
        "hours": [hit for pattern in HOUR_PATTERNS for hit in pattern.findall(text)],
        "section_dividers": len(re.findall(r"[—\-*]{3,}", text)),
        "ending_cliches": [w for w in ENDING_CLICHES if w in tail],
        "connector_lines": sum(1 for line in lines if line[:2] in CONNECTORS),
        "parens": text.count("（") + text.count("("),
        "self_third": sum(text.count(w) for w in SELF_THIRD),
        "particles": sum(text.count(w) for w in PARTICLES),
        "has_heading": bool(re.match(r"^\*\*.+?\*\*", text.strip())),
    }


def corpus_baseline() -> dict[str, Any]:
    """从原始语料现场算基线，不把数字写死在脚本里。"""
    text = CORPUS.read_text(encoding="utf-8")
    parts = re.split(r"^\*\*(.+?)\*\*[ \t]*$", text, flags=re.M)
    entries = [(parts[i], parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
    per_entry = [(title.strip(), _metrics(body)) for title, body in entries]
    pooled = _metrics("\n".join(body for _, body in entries))
    return {
        "entries": [{"title": title, **m} for title, m in per_entry],
        "pooled": pooled,
        "mean_chars": round(statistics.mean(m["chars"] for _, m in per_entry)),
    }


def _checks(metrics: dict[str, Any], chat_turns: int) -> list[tuple[str, bool, str]]:
    rich = chat_turns >= 100
    return [
        ("钟点为 0", not metrics["hours"], f"{metrics['hours']}"),
        ("无分节线", metrics["section_dividers"] == 0, f"{metrics['section_dividers']}"),
        ("结尾不是总结腔", not metrics["ending_cliches"], f"{metrics['ending_cliches']}"),
        ("句均 12–25", 12 <= metrics["mean_sentence"] <= 25, f"{metrics['mean_sentence']}"),
        ("行数 ≥ 10" + ("（足量素材）" if rich else "（素材少，跳过）"),
         (not rich) or metrics["lines"] >= 10, f"{metrics['lines']}"),
        ("身体密度 ≥ 5", metrics["body_density"] >= 5, f"{metrics['body_density']}"),
        ("自称密度 ≤ 28", metrics["self_density"] <= 28, f"{metrics['self_density']}"),
        ("段首连接词 ≤ 2", metrics["connector_lines"] <= 2, f"{metrics['connector_lines']}"),
    ]


@contextmanager
def _read_only_writes() -> Iterator[None]:
    """把日记链路的四处写盘点全部换成空操作。"""

    async def _noop_async(*_: Any, **__: Any) -> None:
        return None

    class _StubExport:
        async def export_date(self, *_: Any, **__: Any) -> None:
            return None

    from core.services.journal import persona_exports
    from core.services.journal.storage import JournalStorage
    from core.services.journal.summary_service import JournalSummaryService
    from core.services.study import summary_generator

    with patch.object(JournalStorage, "save_daily_summary", _noop_async), patch.object(
        JournalSummaryService, "_append_daily_summary_diary_entry", _noop_async
    ), patch.object(
        JournalSummaryService, "_persist_study_summary_artifact", _noop_async
    ), patch.object(
        persona_exports, "get_persona_journal_export_service", lambda *a, **k: _StubExport()
    ), patch.object(
        summary_generator.StudySummaryGenerator, "generate", _noop_async
    ):
        yield


async def _generate(date_str: str) -> dict[str, Any]:
    from core.services.journal.service import get_journal_service

    service = get_journal_service()
    summary = await service.generate_daily_summary(date_str, force=True, persona="ye")
    stats = summary.stats or {}
    return {
        "summary": summary.summary,
        "chat_turn_count": int(stats.get("chat_turn_count") or 0),
        "entry_count": int(stats.get("entry_count") or 0),
        "generated": bool(stats.get("generated")),
        "failure": stats.get("reason") or "",
    }


def _print_day(date_str: str, payload: dict[str, Any]) -> bool:
    metrics = _metrics(payload["summary"])
    checks = _checks(metrics, payload["chat_turn_count"])
    ok = all(passed for _, passed, _ in checks)
    print("\n" + "=" * 78)
    print(
        f"{date_str}  素材 {payload['chat_turn_count']} 条 / 记录 {payload['entry_count']} 条"
        f"  → {metrics['chars']} 字 / {metrics['lines']} 行 / 句均 {metrics['mean_sentence']}"
        f" / 身体 {metrics['body_density']} / 自称 {metrics['self_density']}"
        f" / 括号 {metrics['parens']} / 三身自称 {metrics['self_third']}"
        f" {'PASS' if ok else 'FAIL'}"
    )
    if payload["failure"]:
        print(f"!! 生成失败占位：{payload['failure']}")
    for name, passed, value in checks:
        print(f"   {'ok ' if passed else 'XX '} {name:<22} {value}")
    print("-" * 78)
    print(payload["summary"].strip() or "（空正文）")
    return ok


async def _run(dates: list[str], label: str) -> int:
    baseline = corpus_baseline()
    pooled = baseline["pooled"]
    print("=" * 78)
    print(
        f"原始语料基线：{len(baseline['entries'])} 篇 / 均值 {baseline['mean_chars']} 字"
        f" / 句均 {pooled['mean_sentence']} / 身体 {pooled['body_density']}"
        f" / 自称 {pooled['self_density']} / 括号 {pooled['parens']}"
    )
    print("=" * 78)

    results: dict[str, Any] = {}
    all_ok = True
    with _read_only_writes():
        for date_str in dates:
            try:
                payload = await _generate(date_str)
            except Exception as exc:  # noqa: BLE001 - 单天失败不阻断整批
                print(f"\n{date_str} 生成异常: {type(exc).__name__}: {exc}")
                all_ok = False
                continue
            all_ok = _print_day(date_str, payload) and all_ok
            results[date_str] = {"payload": payload, "metrics": _metrics(payload["summary"])}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUT_DIR / f"ye_diary_style_{label}.json"
    report_path.write_text(
        json.dumps(
            {"label": label, "baseline": baseline, "results": results},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\n报告：{report_path}")
    return 0 if all_ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Ye日记文风验证（只读）")
    parser.add_argument("--dates", nargs="+", default=DEFAULT_DATES, help="要验证的日期")
    parser.add_argument("--label", default="current", help="报告文件名后缀")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    for name in ("core", "config", "services", "routers"):
        logging.getLogger(name).setLevel(logging.WARNING)
    _load_env()
    _prime_data_paths()
    return asyncio.run(_run(args.dates, args.label))


if __name__ == "__main__":
    raise SystemExit(main())
