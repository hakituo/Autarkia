"""学习时长的统一口径。

每日记录 ``study.sessions`` 里的条目有两种形态：

1. **带显式分钟**（``minutes`` 字段）—— 客户端上报的真实前台时长，
   例如背单词计时器。这类条目按字段取值，不再解析正文。
2. **只有正文**（历史数据、聊天里手动记录）—— 沿用 ``"45分钟"`` 的正则兜底。

``count_in_total`` 为 ``False`` 的条目只作为上下文留存（例如服务端按墙钟
估出来的词汇会话摘要），不参与「今日学习时长」，避免与前台计时重复计账。

真源：本模块。``routers/v1/context_daily.py`` 的今日画像与
``core/services/study/study_bridge.py`` 的学习面板都从这里取数。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

_MINUTE_RE = re.compile(r"(\d+)\s*分钟")

#: 客户端背单词计时器写入的条目来源标记。
VOCAB_TIMER_SOURCE = "vocab_timer"


def _study_sessions(record: Any) -> List[Dict[str, Any]]:
    if not isinstance(record, dict):
        return []
    study = record.get("study")
    if not isinstance(study, dict):
        return []
    sessions = study.get("sessions")
    if not isinstance(sessions, list):
        return []
    return [item for item in sessions if isinstance(item, dict)]


def _explicit_minutes(session: Dict[str, Any]) -> int | None:
    """读取条目里的显式分钟；不是合法数字时返回 None。"""
    value = session.get("minutes")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0, int(round(float(value))))


def extract_study_total_minutes(record: Any) -> Tuple[int, List[Dict[str, Any]]]:
    """返回 (今日学习总分钟, 学习会话列表)。

    显式 ``minutes`` 优先；没有该字段时才回退到正文里的「N 分钟」。
    ``count_in_total == False`` 的条目跳过。
    """
    sessions = _study_sessions(record)
    total = 0
    for session in sessions:
        if session.get("count_in_total") is False:
            continue
        explicit = _explicit_minutes(session)
        if explicit is not None:
            total += explicit
            continue
        text = f"{session.get('content') or ''} {session.get('topic') or ''}"
        match = _MINUTE_RE.search(text)
        if match:
            total += int(match.group(1))
    return total, sessions


def vocab_tracked_minutes(record: Any) -> int:
    """客户端计时器今天已上报的词汇分钟数（0 表示还没上报过）。"""
    total = 0
    for session in _study_sessions(record):
        if session.get("source") != VOCAB_TIMER_SOURCE:
            continue
        explicit = _explicit_minutes(session)
        if explicit is not None:
            total += explicit
    return total
