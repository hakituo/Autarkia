"""按「派生来源日期」选新：给按天派生的状态文件用的合并策略。

适用对象是 ``data/study_data/English/Words/daily/_review*_state.json``：它们
都是**当天从进度数据派生**出来的状态（今天锁定哪些词复习），两端各写一份，
内容必然不同。

这类文件的 mtime 没有可比性——一端刚开机，就可能拿**还没同步过来的旧进度**
生成一份全新的文件，mtime 反而比另一端更晚。2026-10-16 实测：Linux 用停在
10-03 的进度生成了 365 条队列（mtime 00:45），Windows 用 10-15 的进度生成了
32 条队列（mtime 00:17），按 mtime 裁决就把错的选了。

真正决定谁对的是**它派生自哪天的数据**，所以这里按：

1. ``source_date``（顶层，或 ``entries`` 里最大的那个）——派生来源的日期；
2. ``selected_at``——同源时的选取时刻；
3. ``version``——兜底。

从新到旧取一份。任一解析不了就返回 None，交回冲突流程按 mtime 处理，
不会因为格式意外而误判。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple


def union_dated_state(left: bytes, right: bytes) -> Optional[bytes]:
    """取派生来源更新的那一份；解析失败返回 None（由调用方按冲突处理）。"""
    mine = _load(left)
    theirs = _load(right)
    if mine is None or theirs is None:
        return None
    if mine == theirs:
        return left
    return left if _freshness(mine) >= _freshness(theirs) else right


def _freshness(state: Dict[str, Any]) -> Tuple[str, str, str]:
    """排序键：来源日期 > 选取时刻 > 版本，均为越大越新。"""
    return (
        _source_date(state),
        str(state.get("selected_at") or "").strip(),
        str(state.get("version") or "").strip(),
    )


def _source_date(state: Dict[str, Any]) -> str:
    """派生来源日期：优先顶层 source_date，否则取 entries 里最大的。

    日期是 ``YYYY/MM/DD``，字符串比较即时间顺序；取最大是因为
    「处理到更晚的每日生词文件」意味着这份状态更新。
    """
    top = str(state.get("source_date") or "").strip()
    if top:
        return top
    entries = state.get("entries")
    if not isinstance(entries, list):
        return ""
    dates = [
        str(item.get("source_date") or "").strip()
        for item in entries
        if isinstance(item, dict)
    ]
    candidates = [value for value in dates if value]
    return max(candidates) if candidates else ""


def _load(raw: bytes) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None
