# -*- coding: utf-8 -*-
"""背单词前台计时：每日记录覆盖写与「今日学习时长」汇总口径。

约定：
- 文件 IO 全部落在 ``tmp_path``，不触碰真实 companion_data/；
- 计划项投影与上报接口见 ``test_vocab_study_time_plan.py``。
"""

from datetime import datetime, timedelta

import pytest

from core.services.daily import daily_entries
from core.services.daily import manager as manager_mod
from core.services.daily.manager import DailyActivityManager
from core.services.daily.study_minutes import (
    VOCAB_TIMER_SOURCE,
    extract_study_total_minutes,
    vocab_tracked_minutes,
)

TODAY = "2026-10-19"


class _Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 10, 19, 9, 0, 0)

    def now_str(self, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        return self.current.strftime(fmt)

    def advance(self, minutes: int) -> None:
        self.current += timedelta(minutes=minutes)


@pytest.fixture
def daily(tmp_path, monkeypatch):
    """数据目录指向 tmp_path、时间固定的 DailyActivityManager。"""
    clock = _Clock()
    monkeypatch.setattr(manager_mod, "get_user_daily_records_dir", lambda: tmp_path)
    monkeypatch.setattr(manager_mod, "today_str", lambda: TODAY)
    monkeypatch.setattr(manager_mod, "now_str", clock.now_str)
    monkeypatch.setattr(daily_entries, "now_str", clock.now_str)
    manager_mod._daily_manager_factory.reset()
    yield DailyActivityManager(), clock
    manager_mod._daily_manager_factory.reset()


# ────────────────────────── 每日记录覆盖写 ──────────────────────────


def test_record_study_same_session_overwrites_and_keeps_first_time(daily):
    manager, clock = daily
    manager.record_study(
        "英语词汇", "背单词 5分钟（复习）", session_id="t1", minutes=5,
        source=VOCAB_TIMER_SOURCE,
    )
    clock.advance(7)
    manager.record_study(
        "英语词汇", "背单词 12分钟（复习）", session_id="t1", minutes=12,
        source=VOCAB_TIMER_SOURCE,
    )

    sessions = manager.get_record(None)["study"]["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["minutes"] == 12
    # 覆盖时保留首次记录时刻，别让「开始学习的时间」漂移到每次上报点
    assert sessions[0]["time"] == "09:00"
    assert sessions[0]["source"] == VOCAB_TIMER_SOURCE
    assert sessions[0]["id"] == "t1"


def test_record_study_different_sessions_append_and_mark_context_only(daily):
    manager, _clock = daily
    manager.record_study(
        "英语词汇", "背单词 3分钟", session_id="t1", minutes=3,
        source=VOCAB_TIMER_SOURCE,
    )
    manager.record_study("英语词汇", "复习用时 30 分钟", count_in_total=False)

    sessions = manager.get_record(None)["study"]["sessions"]
    assert len(sessions) == 2
    assert "minutes" not in sessions[1]
    assert sessions[1]["count_in_total"] is False


# ────────────────────────── 今日学习时长口径 ──────────────────────────


def test_extract_study_total_minutes_prefers_explicit_and_skips_context_only():
    record = {
        "study": {
            "sessions": [
                {"content": "背单词 5分钟", "minutes": 12},
                {"content": "朗读 30分钟"},
                {"content": "复习 45分钟", "minutes": 30, "count_in_total": False},
            ]
        }
    }

    total, sessions = extract_study_total_minutes(record)

    assert total == 42
    assert len(sessions) == 3
    assert extract_study_total_minutes(None) == (0, [])


def test_extract_study_total_minutes_ignores_bad_minutes_and_filters_non_dict():
    record = {
        "study": {
            "sessions": [
                {"content": "写题 20分钟", "minutes": "12"},
                "not-a-dict",
                {"topic": "背诵 15分钟"},
            ]
        }
    }

    total, sessions = extract_study_total_minutes(record)

    assert total == 35
    assert len(sessions) == 2


def test_vocab_tracked_minutes_requires_timer_source_and_explicit_minutes():
    record = {
        "study": {
            "sessions": [
                {"content": "背单词 3分钟", "minutes": 3, "source": VOCAB_TIMER_SOURCE},
                {"content": "背单词 9分钟", "minutes": 9},
                {"content": "背单词 5分钟", "source": VOCAB_TIMER_SOURCE},
            ]
        }
    }

    assert vocab_tracked_minutes(record) == 3
    assert vocab_tracked_minutes(None) == 0
