"""C6/C7 文本匹配与提取质量指标（中文数字归一化、金标覆盖、provenance）。"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

IGNORED_KINDS = frozenset({"skip"})

_ZH_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_ZH_UNITS = {"十": 10, "百": 100, "千": 1000}
# 只转换后面紧跟量词的中文数字，避免把「十分」「一起」这类词语误转
_ZH_NUM_RE = re.compile(
    r"[零〇一二两三四五六七八九十百千]+(?=[元张点月日号岁个次天年人块条份])"
)
_ZH_DATE_HAO_RE = re.compile(r"(?<=\d)号")
_ZH_STANDALONE_NUM_RE = re.compile(r"^[零〇一二两三四五六七八九十百千]+$")


def _zh_run_to_int(run: str) -> Optional[int]:
    total = 0
    section = 0
    number = 0
    for char in run:
        if char in _ZH_DIGITS:
            number = _ZH_DIGITS[char]
        elif char in _ZH_UNITS:
            section += (number or 1) * _ZH_UNITS[char]
            number = 0
        else:
            return None
    total = section + number
    return total if total > 0 else None


def normalize_zh_numbers(text: str) -> str:
    def _replace(match: re.Match) -> str:
        value = _zh_run_to_int(match.group())
        return str(value) if value is not None else match.group()

    return _ZH_NUM_RE.sub(_replace, text)


def norm_text(value: Any) -> str:
    text = str(value or "").lower()
    text = normalize_zh_numbers(text)
    if _ZH_STANDALONE_NUM_RE.fullmatch(text):
        # 关键词本身就是纯中文数字（如「二百四十」）时没有量词可依，单独转换
        converted = _zh_run_to_int(text)
        if converted is not None:
            text = str(converted)
    text = _ZH_DATE_HAO_RE.sub("日", text)
    return "".join(text.split())


def keywords_match(text: Any, keywords: Iterable[str]) -> bool:
    haystack = norm_text(text)
    wanted = [norm_text(item) for item in keywords if norm_text(item)]
    return bool(wanted) and all(item in haystack for item in wanted)


def gold_coverage(
    notes: Sequence[Mapping[str, Any]],
    gold_facts: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    matched: List[str] = []
    for fact_id, fact in gold_facts.items():
        evidence = {str(item) for item in fact.get("evidence_turns") or []}
        for note in notes:
            if note.get("kind") in IGNORED_KINDS:
                continue
            if not keywords_match(note.get("text"), fact.get("keywords") or []):
                continue
            sources = {str(item) for item in note.get("source_turns") or []}
            if evidence & sources:
                matched.append(fact_id)
                break
    total = len(gold_facts)
    return {
        "matched": len(matched),
        "denominator": total,
        "rate": round(len(matched) / total, 4) if total else None,
        "matched_fact_ids": matched,
    }


def supported_note_stats(
    notes: Sequence[Mapping[str, Any]],
    gold_facts: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    valid = [
        note
        for note in notes
        if note.get("kind") not in IGNORED_KINDS and str(note.get("text") or "").strip()
    ]
    supported = 0
    for note in valid:
        if any(
            keywords_match(note.get("text"), fact.get("keywords") or [])
            for fact in gold_facts.values()
        ):
            supported += 1
    total = len(valid)
    return {
        "notes": total,
        "supported": supported,
        "unsupported": total - supported,
        "supported_rate": round(supported / total, 4) if total else None,
    }


def provenance_stats(notes: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    valid = [note for note in notes if note.get("kind") not in IGNORED_KINDS]
    ok = sum(1 for note in valid if note.get("provenance_ok"))
    return {
        "notes": len(valid),
        "provenance_ok": ok,
        "rate": round(ok / len(valid), 4) if valid else None,
    }


def parse_failure_rate(notes: Sequence[Mapping[str, Any]]) -> Optional[float]:
    valid = [note for note in notes if note.get("kind") not in IGNORED_KINDS]
    if not valid:
        return None
    failed = sum(1 for note in valid if note.get("parse_failed"))
    return round(failed / len(valid), 4)


__all__ = [
    "gold_coverage",
    "keywords_match",
    "norm_text",
    "normalize_zh_numbers",
    "parse_failure_rate",
    "provenance_stats",
    "supported_note_stats",
]
