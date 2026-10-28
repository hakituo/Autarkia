"""梗概自动注入的选取规则（纯函数，不读盘）：分类挑选、去重、预算截断、渲染。

口径见 ``.trae/specs/notes_injection_spec.md`` §1、§4。条数与字数上限来自 44 题真实问答集
的离线评测（§1.1）：相关梗概 5 条时证据命中到顶，每条留 100 字保住约九成关键词。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from memory.notes.plan_due import plan_state


@dataclass(frozen=True)
class Quota:
    limit: int  # 条数上限
    chars: int  # 每条正文字数上限


RELEVANT = Quota(limit=5, chars=100)
#: 计划 / 偏好是提取器写的短事实（≤40 字），60 字基本不截
PLAN = Quota(limit=2, chars=60)
PREFERENCE = Quota(limit=3, chars=60)
#: 全部条目正文合计上限（不含标签、编号与标题）
TOTAL_CHARS = 800
PLAN_WINDOW_SECONDS = 14 * 86400
#: 已完成 / 已取消的计划与原计划二元组重合这么多，就当作同一件事收尾了
PLAN_CLOSE_OVERLAP = 0.5
CLOSED_STATUSES = ("done", "cancelled")
#: 梗概的字符二元组有这么多落在已有注入里就算重复
DUP_OVERLAP = 0.6
#: 每类先多取几倍候选，闸门 / 隐私过滤后仍够数
CANDIDATE_FACTOR = 3

HEADER = "【梗概记忆（自动检索，仅供参考）】"
FOOTER = (
    "（梗概可能不完整或写偏；需要原话时用 expand_memory 展开行尾编号，"
    "或用 search_chat_history 查原始聊天记录）"
)
SECTION_TITLES = {"relevant": "相关：", "plan": "近期计划：", "preference": "偏好："}
_QUOTAS = {"relevant": RELEVANT, "plan": PLAN, "preference": PREFERENCE}


def _ts(note: Mapping[str, Any], *keys: str) -> float:
    for key in keys:
        try:
            value = float(note.get(key) or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value:
            return value
    return 0.0


def _when(note: Mapping[str, Any]) -> float:
    return _ts(note, "occurred_to", "occurred_from")


def _importance(note: Mapping[str, Any]) -> float:
    try:
        return float(note.get("importance") or 0)
    except (TypeError, ValueError):
        return 0.0


def _bigrams(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", str(text or ""))
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def plan_pool(notes: Iterable[Mapping[str, Any]], now: float) -> list[dict[str, Any]]:
    """窗口内的全部 plan（含已完成 / 已取消的收尾条目），供过闸门后再挑。

    14 天前说的、但到期日还没到的计划也算在窗口内（「下个月底交论文」）。
    """
    cutoff = now - PLAN_WINDOW_SECONDS
    return [
        dict(n)
        for n in notes
        if n.get("kind") == "plan" and (_when(n) >= cutoff or _ts(n, "valid_to") >= now)
    ]


def _closed_by(plan: Mapping[str, Any], closers: Sequence[Mapping[str, Any]]) -> bool:
    grams = _bigrams(plan.get("text") or "")
    if not grams:
        return False
    for closer in closers:
        if _when(closer) < _ts(plan, "occurred_from", "occurred_to"):
            continue  # 收尾必须发生在计划之后
        other = _bigrams(closer.get("text") or "")
        if other and len(grams & other) / min(len(grams), len(other)) >= PLAN_CLOSE_OVERLAP:
            return True
    return False


def pick_plans(notes: Iterable[Mapping[str, Any]], now: float) -> list[dict[str, Any]]:
    """未完成的近期计划，按时间倒序：done / cancelled / 过了到期日的不要，被后来的收尾条目对上的也不要。

    v8 及更早的 plan 没有 status，按 open 处理。
    """
    pool = plan_pool(notes, now)
    closers = [n for n in pool if n.get("status") in CLOSED_STATUSES]
    plans = [n for n in pool if plan_state(n, now) == "open" and not _closed_by(n, closers)]
    plans.sort(key=lambda n: (-_when(n), str(n.get("note_id"))))
    return plans[: PLAN.limit * CANDIDATE_FACTOR]


def pick_preferences(notes: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """偏好按重要度、时间倒序（不设硬门槛：v8 的短事实重要度全是 0.5，门槛会让这栏永远空）。"""
    prefs = [dict(n) for n in notes if n.get("kind") == "preference"]
    prefs.sort(key=lambda n: (-_importance(n), -_when(n), str(n.get("note_id"))))
    return prefs[: PREFERENCE.limit * CANDIDATE_FACTOR]


def clip(text: str, limit: int) -> str:
    text = _norm(text)
    return text if len(text) <= limit else text[: max(limit - 1, 0)] + "…"


def compose(
    sections: Mapping[str, Sequence[Mapping[str, Any]]], existing: Sequence[str]
) -> list[tuple[str, dict[str, Any], str]]:
    """按 相关 → 计划 → 偏好 的优先级装入，返回 ``(类别, 梗概, 截断后正文)``。

    去重：同 note_id、同规范化正文、与已有注入（及已选梗概）二元组重合 ≥ 60% 的跳过。
    预算：每类条数 / 每条字数上限，总正文 ≤ 800 字，装不下即停（丢低优先级的末尾）。
    """
    seen_ids: set[str] = set()
    seen_texts: set[str] = set()
    covered: set[str] = set()
    for text in existing:
        covered |= _bigrams(text)
    picked: list[tuple[str, dict[str, Any], str]] = []
    used = 0
    for section in ("relevant", "plan", "preference"):
        quota = _QUOTAS[section]
        count = 0
        for note in sections.get(section) or ():
            if count >= quota.limit:
                break
            note_id = str(note.get("note_id") or "")
            norm = _norm(note.get("text") or "")
            if not norm or note_id in seen_ids or norm in seen_texts:
                continue
            grams = _bigrams(norm)
            if grams and len(grams & covered) / len(grams) >= DUP_OVERLAP:
                continue
            text = clip(norm, quota.chars)
            if used + len(text) > TOTAL_CHARS:
                return picked
            picked.append((section, dict(note), text))
            used += len(text)
            count += 1
            seen_ids.add(note_id)
            seen_texts.add(norm)
            covered |= grams
    return picked


def render(picked: Sequence[tuple[str, Mapping[str, Any], str]]) -> str:
    """渲染成一个注入块；没有条目时返回空串（调用方据此不注入）。

    每行末尾带梗概短编号，模型觉得梗概不够时可以凭编号回查原话（兜底）。
    """
    if not picked:
        return ""
    from core.tools.expand_memory_tool import note_ref_suffix
    from core.tools.memory_notes_search import note_label

    lines = [HEADER]
    current = None
    for section, note, text in picked:
        if section != current:
            lines.append(SECTION_TITLES[section])
            current = section
        entry = {
            "category": note.get("kind") or "episode",
            "occurred_to": note.get("occurred_to"),
            "status": note.get("status"),
        }
        # 偏好不带时间（省字数，时间对偏好意义不大）
        if section != "preference":
            entry["timestamp"] = note.get("occurred_from")
        lines.append(f"- {note_label(entry)} {text}{note_ref_suffix(note.get('note_id'))}")
    lines.append(FOOTER)
    return "\n".join(lines)


__all__ = [
    "PLAN",
    "PREFERENCE",
    "RELEVANT",
    "TOTAL_CHARS",
    "clip",
    "compose",
    "pick_plans",
    "pick_preferences",
    "plan_pool",
    "render",
]
