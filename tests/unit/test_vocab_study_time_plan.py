# -*- coding: utf-8 -*-
"""背单词前台计时：计划项替换式投影与 /vocab/study-time 上报接口。

计划侧用假 journal（与 test_focus_plan_execution_loop.py 同款），离线跑。
"""

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from core.services.daily.study_minutes import VOCAB_TIMER_SOURCE
from core.services.journal.models import DailyPlan, PlanItem
from core.services.journal.plan_crud import PlanCRUDService

TODAY = "2026-10-19"


# ────────────────────────── 计划项替换式投影 ──────────────────────────


class _FakeStorage:
    def __init__(self, plan: DailyPlan):
        self.plan = plan
        self.save_count = 0

    async def get_plan(self, _dt, scope="user"):
        assert scope == "user"
        return self.plan

    async def save_plan(self, plan, _dt, scope="user"):
        assert scope == "user"
        self.plan = plan
        self.save_count += 1


class _FakeJournalService:
    def __init__(self, plan: DailyPlan):
        self.storage = _FakeStorage(plan)

    @staticmethod
    def _parse_date(date_str):
        return datetime.strptime(date_str, "%Y-%m-%d")


def _vocab_plan(**overrides) -> DailyPlan:
    fields = {
        "id": "plan_vocab",
        "title": "复习到期英语词汇（20 个）",
        "source_key": "vocab:due_review",
        "estimated_duration_minutes": 45,
    }
    fields.update(overrides)
    return DailyPlan(date=TODAY, items=[PlanItem(**fields)])


def test_apply_vocab_study_time_replaces_instead_of_accumulating():
    plan = _vocab_plan()
    item = plan.items[0]
    crud = PlanCRUDService(_FakeJournalService(plan))

    asyncio.run(crud.apply_vocab_study_time(TODAY, 5))
    assert (item.actual_minutes, item.vocab_minutes) == (5.0, 5.0)
    assert item.status == "in_progress"

    asyncio.run(crud.apply_vocab_study_time(TODAY, 12))
    assert item.actual_minutes == 12.0
    assert item.vocab_minutes == 12.0


def test_apply_vocab_study_time_keeps_focus_minutes():
    plan = _vocab_plan(actual_minutes=20.0)
    item = plan.items[0]
    crud = PlanCRUDService(_FakeJournalService(plan))

    asyncio.run(crud.apply_vocab_study_time(TODAY, 12))
    assert item.actual_minutes == 32.0
    assert item.vocab_minutes == 12.0

    # 第二次上报只替换词汇部分：20（Focus）+ 15（新词汇）而不是 20 + 12 + 15
    asyncio.run(crud.apply_vocab_study_time(TODAY, 15))
    assert item.actual_minutes == 35.0
    assert item.vocab_minutes == 15.0


@pytest.mark.parametrize("status", ["completed", "skipped"])
def test_apply_vocab_study_time_does_not_downgrade_terminal_status(status):
    plan = _vocab_plan(status=status)
    item = plan.items[0]
    crud = PlanCRUDService(_FakeJournalService(plan))

    asyncio.run(crud.apply_vocab_study_time(TODAY, 8))

    assert item.status == status
    assert item.vocab_minutes == 8.0


def test_apply_vocab_study_time_zero_minutes_keeps_pending():
    plan = _vocab_plan()
    item = plan.items[0]
    crud = PlanCRUDService(_FakeJournalService(plan))

    asyncio.run(crud.apply_vocab_study_time(TODAY, 0))

    assert item.actual_minutes == 0.0
    assert item.status == "pending"


def test_apply_vocab_study_time_without_vocab_item_is_noop():
    plan = DailyPlan(
        date=TODAY,
        items=[PlanItem(id="plan_math", title="数学 · 三角函数", actual_minutes=0.0)],
    )
    service = _FakeJournalService(plan)
    crud = PlanCRUDService(service)

    asyncio.run(crud.apply_vocab_study_time(TODAY, 12))

    assert service.storage.plan.items[0].actual_minutes == 0.0
    assert service.storage.save_count == 0


# ────────────────────────── 上报接口 ──────────────────────────


class _FakeDaily:
    def __init__(self):
        self.record = {"date": TODAY, "study": {"sessions": [], "summary": ""}}
        self.calls = []

    def record_study(
        self, topic, content, *, session_id=None, minutes=None,
        count_in_total=True, source=None,
    ):
        self.calls.append(
            {
                "topic": topic,
                "content": content,
                "session_id": session_id,
                "minutes": minutes,
                "count_in_total": count_in_total,
                "source": source,
            }
        )
        sessions = self.record["study"]["sessions"]
        entry = {"topic": topic, "content": content, "time": "09:00"}
        if session_id:
            entry["id"] = session_id
        if minutes is not None:
            entry["minutes"] = minutes
        for index, existing in enumerate(sessions):
            if session_id and existing.get("id") == session_id:
                sessions[index] = entry
                return
        sessions.append(entry)

    def get_record(self, _date_str=None):
        return self.record


class _FakeJournal:
    def __init__(self):
        self.calls = []

    async def apply_vocab_study_time(self, date, minutes):
        self.calls.append((date, minutes))
        item = SimpleNamespace(
            source_key="vocab:due_review",
            title="复习到期英语词汇",
            actual_minutes=float(minutes),
        )
        return SimpleNamespace(items=[item])


@pytest.fixture
def vocab_route(monkeypatch):
    import routers.v1.vocab_study_time as route

    daily = _FakeDaily()
    journal = _FakeJournal()
    monkeypatch.setattr(route, "today_str", lambda: TODAY)
    monkeypatch.setattr("core.services.daily.manager.get_daily_manager", lambda: daily)
    monkeypatch.setattr("core.services.journal.service.get_journal_service", lambda: journal)
    return route, daily, journal


def test_report_requires_session_id(vocab_route):
    route, daily, _journal = vocab_route

    result = asyncio.run(route.report_vocab_study_time({"seconds": 60}))

    assert result["status"] == "error"
    assert result["error_code"] == "MISSING_PARAMETER"
    assert daily.calls == []


def test_report_zero_seconds_returns_day_total_without_writing(vocab_route):
    route, daily, journal = vocab_route
    daily.record["study"]["sessions"].append({"content": "朗读 30分钟"})

    result = asyncio.run(
        route.report_vocab_study_time({"session_id": "abc", "seconds": 0})
    )

    assert result["status"] == "success"
    assert result["data"]["minutes"] == 0
    assert result["data"]["day_total_minutes"] == 30
    assert result["data"]["plan_actual_minutes"] is None
    assert daily.calls == []
    assert journal.calls == []


def test_report_rounds_thirty_seconds_to_one_minute(vocab_route):
    route, _daily, _journal = vocab_route

    result = asyncio.run(
        route.report_vocab_study_time({"session_id": "half", "seconds": 30})
    )

    assert result["data"]["minutes"] == 1


def test_report_overwrites_by_session_id_and_projects_to_plan(vocab_route):
    route, daily, journal = vocab_route

    asyncio.run(
        route.report_vocab_study_time(
            {"session_id": "abc", "seconds": 300, "mode": "review"}
        )
    )
    result = asyncio.run(
        route.report_vocab_study_time(
            {"session_id": "abc", "seconds": 720, "mode": "review"}
        )
    )

    sessions = daily.record["study"]["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["minutes"] == 12
    assert daily.calls[-1]["session_id"] == f"vocab_timer:{TODAY}:abc"
    assert daily.calls[-1]["source"] == VOCAB_TIMER_SOURCE
    assert result["data"]["day_total_minutes"] == 12
    assert result["data"]["plan_actual_minutes"] == 12.0
    # 每次上报都投影一次，服务端按累计值替换，而不是累加
    assert journal.calls == [(TODAY, 5), (TODAY, 12)]
