"""梗概里的相对时间补具体日期（不调模型）：「明天」→「明天（9月26日）」。

时间题常按具体日期问（「9 月 26 日我去做什么了」），梗概里却只有说话当时的「明天」「昨晚」，
检索和回答都对不上；让模型自己注明日期执行率只有约 5%（2026-10-28 aveline 12 段验证），
所以由代码按这条梗概所依据往来的时间推算。

- 参照时间 = 梗概的 ``occurred_from``（它依据的第一次往来），时区与 search_memory 时间标签一致；
- 凌晨 5 点前说的「今天 / 明天 / 今晚」按前一天算（熬夜时的「明天」通常指天亮后的当天）；
- 只补能确定到某一天的说法：今天 / 明天 / 后天 / 大后天 / 昨天 / 前天 / 大前天（含早晚变体）、
  这周X / 下周X / 上周X；「周末」「月底」「下个月」这类范围说法不补；
- 已经带「（…月…日）」的不重复补；结果确定，同一输入永远得到同一输出。
"""

from __future__ import annotations

import re
from datetime import date, timedelta

#: 凌晨这个钟点前算前一天
NIGHT_CUTOFF_HOUR = 5
_WEEK = "一二三四五六日天"
_DAY_OFFSETS = {
    "大前天": -3, "大后天": 3, "前天": -2, "后天": 2,
    "昨天": -1, "昨日": -1, "昨晚": -1, "昨夜": -1, "昨早": -1,
    "今天": 0, "今日": 0, "今晚": 0, "今早": 0, "今夜": 0,
    "明天": 1, "明日": 1, "明晚": 1, "明早": 1,
}
_WEEK_SHIFT = {"这": 0, "本": 0, "下": 1, "上": -1}
#: 复合词 / 非时间用法，只对对应的词排除：「明日方舟」「今日头条」「明日香」；「先天后天」「后天形成」
_NOT_TIME_AFTER = {
    "今日": ("方舟", "香", "头条", "之星", "之子", "新闻"),
    "明日": ("方舟", "香", "头条", "之星", "之子", "新闻"),
    "后天": ("性", "形成", "养成", "培养", "习得", "努力", "因素"),
}
_NOT_TIME_BEFORE = {"后天": ("先天", "先天与", "先天和")}
#: 长的写在前面，避免「大后天」被拆成「后天」
_PATTERN = re.compile(
    "("
    + "|".join(sorted(_DAY_OFFSETS, key=len, reverse=True))
    + r"|(?:这|本|下|上)(?:周|礼拜|星期)[一二三四五六日天])"
    + r"(?![（(]\d|[（(][^）)]{0,6}月)"
)


def _is_time_usage(text: str, match: re.Match[str]) -> bool:
    phrase = match.group(1)
    after = text[match.end() : match.end() + 3]
    before = text[max(0, match.start() - 3) : match.start()]
    if any(after.startswith(word) for word in _NOT_TIME_AFTER.get(phrase, ())):
        return False
    return not any(before.endswith(word) for word in _NOT_TIME_BEFORE.get(phrase, ()))


def reference_date(timestamp: float) -> tuple[date, int]:
    """(说话那天, 钟点)；与 search_memory 时间标签同一时区口径。"""
    from core.utils.time_utils import format_timestamp

    year, month, day, hour = (int(x) for x in format_timestamp(float(timestamp), "%Y|%m|%d|%H").split("|"))
    return date(year, month, day), hour


def resolve(phrase: str, today: date, hour: int) -> date | None:
    """单个相对说法 → 具体日期；范围说法或认不出时为 None。"""
    if phrase in _DAY_OFFSETS:
        base = today - timedelta(days=1) if hour < NIGHT_CUTOFF_HOUR else today
        return base + timedelta(days=_DAY_OFFSETS[phrase])
    shift = _WEEK_SHIFT.get(phrase[0])
    weekday = _WEEK.find(phrase[-1])
    if shift is None or weekday < 0:
        return None
    weekday = min(weekday, 6)  # 周日 / 周天
    monday = today - timedelta(days=today.weekday())
    return monday + timedelta(days=7 * shift + weekday)


def annotate(text: str, timestamp: float | None) -> str:
    """给相对时间补「（X月X日）」；没有参照时间或没有可补的说法时原样返回。"""
    if not text or not timestamp:
        return text
    today, hour = reference_date(timestamp)

    def repl(match: re.Match[str]) -> str:
        phrase = match.group(1)
        if not _is_time_usage(text, match):
            return phrase
        target = resolve(phrase, today, hour)
        return f"{phrase}（{target.month}月{target.day}日）" if target else phrase

    return _PATTERN.sub(repl, text)


__all__ = ["NIGHT_CUTOFF_HOUR", "annotate", "reference_date", "resolve"]
