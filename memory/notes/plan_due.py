"""计划的到期日与过期判断（不调模型）。

- ``due_timestamp``：从 plan 正文里找能确定到某一天的时间说法，取最晚的那天当到期日，
  返回那天 23:59:59 的时间戳，写进笔记的 ``valid_to``。参照时间是这条计划依据的第一次往来，
  时区口径与 ``dates`` 相同。
- 认的说法：``dates`` 里的「明天 / 今晚 / 下周三」等；写死的「10月30日」「2027年3月5号」
  （含 ``dates.annotate`` 补的「（10月29日）」）；单独的「周三 / 星期三」（今天或之后最近的那天）；
  「周末 / 下周末」（那周的周日）；「月底 / 下个月底」。早于说话那天的日期不算到期日。
- ``plan_state``：读时算出的计划状态。模型标的 done / cancelled 优先；open 的计划过了到期日
  ``GRACE_DAYS`` 天，或者没有到期日、说出来已经 ``NO_DUE_DAYS`` 天，就算 expired。
  过期只在读的时候算，不写回库里（重跑提取会整段替换，写回的状态会丢）。
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from .dates import _PATTERN as _RELATIVE
from .dates import NIGHT_CUTOFF_HOUR, _is_time_usage, resolve

#: 过了到期日这么多天才算过期（留两天让角色还能问一句「那件事弄完了吗」）
GRACE_DAYS = 2
#: 没有到期日的 open 计划，说出来这么多天后算过期
NO_DUE_DAYS = 30
CLOSED_STATUSES = ("done", "cancelled")
EXPIRED = "expired"
#: 写死的日期隔了这么多天之前，按明年算（「1月5日」在 12 月说的指明年）
_PAST_TOLERANCE_DAYS = 60

_WEEK = "一二三四五六日天"
_EXPLICIT = re.compile(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日号]")
_BARE_WEEKDAY = re.compile(r"(?<![这本下上])(?:周|星期|礼拜)([一二三四五六日天])")
_WEEKEND = re.compile(r"(下)?(?:个)?周末")
_MONTH_END = re.compile(r"(下)?(?:个)?月底")


def _base(today: date, hour: int) -> date:
    """熬夜时（凌晨 5 点前）说的话按前一天算，与 ``dates.resolve`` 一致。"""
    return today - timedelta(days=1) if hour < NIGHT_CUTOFF_HOUR else today


def _explicit_dates(text: str, base: date) -> list[date]:
    found = []
    for match in _EXPLICIT.finditer(text):
        month, day = int(match.group(2)), int(match.group(3))
        years = (
            [int(match.group(1))] if match.group(1) else [base.year - 1, base.year, base.year + 1]
        )
        candidates = []
        for year in years:
            try:
                candidates.append(date(year, month, day))
            except ValueError:
                continue
        if not match.group(1):
            # 没写年份：取离说话那天最近、且不早于 60 天前的那一年
            # （12 月说「1月5日」是明年；1 月说「12月28日」是去年，随后按过去的日期丢掉）
            floor = base - timedelta(days=_PAST_TOLERANCE_DAYS)
            candidates = [d for d in candidates if d >= floor][:1]
        found.extend(candidates[:1])
    return found


def _relative_dates(text: str, today: date, hour: int) -> list[date]:
    found = []
    for match in _RELATIVE.finditer(text):
        if _is_time_usage(text, match):
            target = resolve(match.group(1), today, hour)
            if target:
                found.append(target)
    return found


def _range_dates(text: str, base: date) -> list[date]:
    found = []
    for match in _BARE_WEEKDAY.finditer(text):
        weekday = min(_WEEK.find(match.group(1)), 6)
        found.append(base + timedelta(days=(weekday - base.weekday()) % 7))
    for match in _WEEKEND.finditer(text):
        sunday = base + timedelta(days=6 - base.weekday())
        found.append(sunday + timedelta(days=7) if match.group(1) else sunday)
    for match in _MONTH_END.finditer(text):
        year, month = base.year, base.month + (1 if match.group(1) else 0)
        if month > 12:
            year, month = year + 1, 1
        found.append(date(year, month, calendar.monthrange(year, month)[1]))
    return found


def due_date(text: str, timestamp: float | None) -> date | None:
    """plan 正文 → 到期日（最晚的一天）；没有能确定到某天的说法时为 None。"""
    if not text or not timestamp:
        return None
    from .dates import reference_date

    today, hour = reference_date(timestamp)
    base = _base(today, hour)
    found = [
        *_explicit_dates(text, base),
        *_relative_dates(text, today, hour),
        *_range_dates(text, base),
    ]
    found = [d for d in found if d >= base]
    return max(found) if found else None


def due_timestamp(text: str, timestamp: float | None) -> float | None:
    """到期日那天 23:59:59 的时间戳（与 ``dates`` 同一时区口径）。"""
    target = due_date(text, timestamp)
    if target is None or not timestamp:
        return None
    from core.utils.time_utils import format_timestamp

    year, month, day, hour, minute, second = (
        int(x) for x in format_timestamp(float(timestamp), "%Y|%m|%d|%H|%M|%S").split("|")
    )
    midnight = float(timestamp) - (hour * 3600 + minute * 60 + second)
    return midnight + (target - date(year, month, day)).days * 86400 + 86399


def _number(note: Mapping[str, Any], *keys: str) -> float:
    for key in keys:
        try:
            value = float(note.get(key) or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value:
            return value
    return 0.0


def plan_state(note: Mapping[str, Any], now: float) -> str:
    """计划在 ``now`` 时的状态：done / cancelled / expired / open；非 plan 原样返回 status。"""
    status = str(note.get("status") or "")
    if note.get("kind") != "plan" or status in CLOSED_STATUSES:
        return status
    due = _number(note, "valid_to")
    if due:
        return EXPIRED if now > due + GRACE_DAYS * 86400 else "open"
    said = _number(note, "occurred_from", "occurred_to")
    if said and now - said > NO_DUE_DAYS * 86400:
        return EXPIRED
    return "open"


__all__ = [
    "CLOSED_STATUSES",
    "EXPIRED",
    "GRACE_DAYS",
    "NO_DUE_DAYS",
    "due_date",
    "due_timestamp",
    "plan_state",
]
