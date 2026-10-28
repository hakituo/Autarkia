"""按段提取器的输出解析：梗概（v5 单条 / v7 按话题多条 / v8 带重要度）、短事实、skip 原因与画像信号。"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
#: 单段最多保留的话题条数（防止模型逐句拆条）
MAX_TOPICS = 12


class EpisodeParseError(ValueError):
    """模型输出既不是梗概也不是明确的 skip。"""


def parse_episode(text: str) -> tuple[str, str]:
    """返回 (梗概, skip 原因)；两者都没有就抛错。"""
    data = _load(text)
    summary = str(data.get("summary") or "").strip()
    skip = str(data.get("skip") or "").strip()
    if summary:
        return summary, ""
    if skip:
        return "", skip
    raise EpisodeParseError("empty_summary_without_skip")


def _string_list(value: Any, limit: int = 12) -> list[str]:
    items = value if isinstance(value, list) else []
    cleaned: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and len(text) <= 20 and text not in cleaned:
            cleaned.append(text)
    return cleaned[:limit]


def parse_signals(text: str) -> dict[str, Any]:
    """画像信号（与旧蒸馏 ``distillation_metadata`` 同名字段）；缺字段视为未分析。"""
    raw = _FENCE.sub("", str(text or "").strip()).strip()
    start, end = raw.find("{"), raw.rfind("}")
    try:
        data = json.loads(raw[start : end + 1]) if 0 <= start < end else {}
    except json.JSONDecodeError:
        data = {}
    data = data if isinstance(data, dict) else {}
    analyzed = "people" in data and "role_updates" in data
    return {
        "profile_signal_analyzed": analyzed,
        "people_mentions": _string_list(data.get("people")),
        "role_update_candidates": _string_list(data.get("role_updates")),
    }


def _load(text: str) -> dict[str, Any]:
    raw = _FENCE.sub("", str(text or "").strip()).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise EpisodeParseError("no_json")
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise EpisodeParseError("bad_json") from exc
    if not isinstance(data, dict):
        raise EpisodeParseError("not_object")
    return data


def _ids(value: Any, exchange_count: int) -> list[int]:
    picked: set[int] = set()
    for item in value if isinstance(value, list) else []:
        try:
            index = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= index < exchange_count:
            picked.add(index)
    return sorted(picked)


#: 每段最多保留的短事实条数；单条上限（字）
MAX_FACTS = 5
MAX_FACT_CHARS = 80
FACT_KINDS = ("fact", "preference", "plan")
#: plan 的状态：open 未做 / done 做完 / cancelled 取消
PLAN_STATUSES = ("open", "done", "cancelled")
#: 模型的 1–3 档重要度 → 笔记 importance；缺省按 2 档
IMPORTANCE_LEVELS = {1: 0.3, 2: 0.5, 3: 0.8}


def _importance(value: Any) -> float:
    try:
        level = int(value)
    except (TypeError, ValueError):
        return IMPORTANCE_LEVELS[2]
    return IMPORTANCE_LEVELS.get(min(max(level, 1), 3), IMPORTANCE_LEVELS[2])


def parse_topic_items(
    text: str, exchange_count: int
) -> tuple[list[tuple[list[int], str, float]], str]:
    """返回 ([(往来编号, 梗概, importance), ...], skip 原因)。

    v7/v8 格式 ``topics``；编号越界的丢掉，全部越界或缺失时按整段算（不因编号错丢梗概）。
    没有 ``topics`` 时兼容 v5/v6 的 ``summary`` 单条格式；什么都没有就抛错（编排层记 failed）。
    """
    data = _load(text)
    topics = data.get("topics")
    if isinstance(topics, list):
        everything = list(range(exchange_count))
        parsed: list[tuple[list[int], str, float]] = []
        for topic in topics[:MAX_TOPICS]:
            if not isinstance(topic, dict):
                continue
            summary = str(topic.get("summary") or "").strip()
            if summary:
                ids = _ids(topic.get("ids"), exchange_count) or everything
                parsed.append((ids, summary, _importance(topic.get("importance"))))
        if parsed:
            return parsed, ""
        skip = str(data.get("skip") or "").strip()
        if skip:
            return [], skip
        raise EpisodeParseError("empty_topics_without_skip")
    summary, skip = parse_episode(text)
    default = IMPORTANCE_LEVELS[2]
    return ([(list(range(exchange_count)), summary, default)] if summary else []), skip


def parse_topics(text: str, exchange_count: int) -> tuple[list[tuple[list[int], str]], str]:
    """v7 口径：([(往来编号, 梗概), ...], skip 原因)。"""
    items, skip = parse_topic_items(text, exchange_count)
    return [(ids, summary) for ids, summary, _importance in items], skip


def parse_facts(text: str, exchange_count: int) -> list[tuple[str, list[int], str]]:
    """v8 口径：[(kind, 往来编号, 短事实), ...]。"""
    return [item[:3] for item in parse_fact_items(text, exchange_count)]


def _plan_status(kind: str, value: Any) -> str:
    """plan 的状态；不认识或缺省按 open（v8 没有这个字段），其它 kind 为空串。"""
    if kind != "plan":
        return ""
    status = str(value or "").strip().lower()
    return status if status in PLAN_STATUSES else "open"


def parse_fact_items(
    text: str, exchange_count: int
) -> list[tuple[str, list[int], str, float, str]]:
    """v9 ``facts``：[(kind, 往来编号, 短事实, importance, plan 状态), ...]。

    kind 不认识、文本为空或过长、编号全缺的都丢掉（短事实必须能回到原话），解析失败返回空。
    """
    try:
        data = _load(text)
    except EpisodeParseError:
        return []
    picked: list[tuple[str, list[int], str, float, str]] = []
    seen: set[str] = set()
    for item in data.get("facts") if isinstance(data.get("facts"), list) else []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        fact = str(item.get("text") or "").strip()
        ids = _ids(item.get("ids"), exchange_count)
        if kind not in FACT_KINDS or not fact or len(fact) > MAX_FACT_CHARS or not ids:
            continue
        if fact in seen:
            continue
        seen.add(fact)
        status = _plan_status(kind, item.get("status"))
        picked.append((kind, ids, fact, _importance(item.get("importance")), status))
        if len(picked) >= MAX_FACTS:
            break
    return picked


def parse_open_ids(text: str, exchange_count: int) -> set[int]:
    """v10 接力：标了 ``"open": true`` 的话题覆盖的往来编号（并集）；解析失败返回空。"""
    try:
        data = _load(text)
    except EpisodeParseError:
        return set()
    topics = data.get("topics") if isinstance(data.get("topics"), list) else []
    return {
        index
        for topic in topics
        if isinstance(topic, dict) and topic.get("open") is True
        for index in _ids(topic.get("ids"), exchange_count)
    }


__all__ = [
    "FACT_KINDS",
    "IMPORTANCE_LEVELS",
    "MAX_FACTS",
    "MAX_TOPICS",
    "PLAN_STATUSES",
    "EpisodeParseError",
    "parse_episode",
    "parse_fact_items",
    "parse_facts",
    "parse_open_ids",
    "parse_signals",
    "parse_topic_items",
    "parse_topics",
]
