"""Active Care 历史时效过滤的回归测试。

覆盖重点：长时间不对话后，不能把很久以前的话题当成「最近上下文」喂给 LLM
（实测：12 天前聊过的溃疡被当成当前话题追问）。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.services.active_care.core.context_builder import TriggerContextBuilder  # noqa: E402
from core.services.active_care.shared.tuning import (  # noqa: E402
    RECENT_HISTORY_MAX_AGE_SECONDS,
)

drop_stale_history = TriggerContextBuilder.drop_stale_history

NOW = 1_800_000_000.0
TEXT = "【最近聊天记录】\n- User: 溃疡别老想它，越关注越疼\n"


def _msg(age_seconds: float, content: str = "溃疡别老想它"):
    return {"role": "user", "content": content, "timestamp": NOW - age_seconds}


def test_recent_history_is_kept_when_within_window():
    msgs = [_msg(3600), _msg(60)]
    assert drop_stale_history(TEXT, msgs, NOW) == TEXT


def test_stale_history_is_replaced_with_notice():
    """整体过旧时不再给内容，只留一句说明。"""
    out = drop_stale_history(TEXT, [_msg(12 * 24 * 3600)], NOW, "shared__scope__aveline")

    assert "溃疡" not in out
    assert "早已结束" in out
    assert "不要延续" in out


def test_latest_message_decides():
    """只要最新一条还在时效内，整段历史照常保留（老消息不单独剔除）。"""
    msgs = [_msg(12 * 24 * 3600, "很久以前的溃疡"), _msg(120, "刚聊的事")]
    assert drop_stale_history(TEXT, msgs, NOW) == TEXT


def test_threshold_boundary():
    inside = [_msg(RECENT_HISTORY_MAX_AGE_SECONDS - 1)]
    outside = [_msg(RECENT_HISTORY_MAX_AGE_SECONDS + 1)]

    assert drop_stale_history(TEXT, inside, NOW) == TEXT
    assert drop_stale_history(TEXT, outside, NOW) != TEXT


def test_missing_timestamp_never_drops_history():
    """拿不到时间戳时不误伤：宁可保留，也不清空。"""
    assert drop_stale_history(TEXT, [{"role": "user", "content": "x"}], NOW) == TEXT
    assert drop_stale_history(TEXT, [], NOW) == TEXT
    assert drop_stale_history(TEXT, None, NOW) == TEXT
