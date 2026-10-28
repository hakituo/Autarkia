"""计划到期日（不调模型）：解析规则、读时过期、提取时写 valid_to、注入过滤、旧数据回填。"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from core.utils import time_utils
from memory.nightly.segment_jobs.contracts import NoteDraft
from memory.notes import NoteStore, paths
from memory.notes.injection import selection as sel
from memory.notes.plan_due import (
    EXPIRED,
    GRACE_DAYS,
    NO_DUE_DAYS,
    due_date,
    due_timestamp,
    plan_state,
)
from scripts.maintenance import backfill_plan_due

SHANGHAI = timezone(timedelta(hours=8))
CONV = "web_role_aveline"
DAY = 86400.0


@pytest.fixture(autouse=True)
def fixed_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        time_utils,
        "format_timestamp",
        lambda ts, fmt="%Y-%m-%d %H:%M:%S": datetime.fromtimestamp(ts, SHANGHAI).strftime(fmt),
    )


def _ts(*args: int) -> float:
    return datetime(*args, tzinfo=SHANGHAI).timestamp()


#: 2025-09-25 是周四
THURSDAY_NIGHT = _ts(2025, 9, 25, 22, 0)


def test_relative_and_annotated_dates() -> None:
    assert due_date("Master明晚之前写好创新点", THURSDAY_NIGHT) == date(2025, 9, 26)
    assert due_date("Master明晚（9月26日）之前写好创新点", THURSDAY_NIGHT) == date(2025, 9, 26)
    assert due_date("Master下周三去成都出差", THURSDAY_NIGHT) == date(2025, 10, 1)
    assert due_date("Master今晚早点睡", THURSDAY_NIGHT) == date(2025, 9, 25)


def test_explicit_dates_with_year_rollover() -> None:
    assert due_date("Master10月30日交论文", THURSDAY_NIGHT) == date(2025, 10, 30)
    assert due_date("Master2026年3月5号考试", THURSDAY_NIGHT) == date(2026, 3, 5)
    # 12 月说「1月5日」指明年
    assert due_date("Master1月5日回家", _ts(2025, 12, 20, 12, 0)) == date(2026, 1, 5)
    assert due_date("Master2月30日去玩", THURSDAY_NIGHT) is None
    # 1 月说「12月28日」是去年的事，不当到期日（不能算成年底）
    assert due_date("Master12月28日说要补卷子", _ts(2026, 1, 3, 12, 0)) is None
    assert due_date("Master2月29日去玩", _ts(2027, 12, 1, 12, 0)) == date(2028, 2, 29)


def test_bare_weekday_weekend_and_month_end() -> None:
    assert due_date("Master周六去爬山", THURSDAY_NIGHT) == date(2025, 9, 27)
    assert due_date("Master星期四交作业", THURSDAY_NIGHT) == date(2025, 9, 25)  # 当天
    assert due_date("Master周二复诊", THURSDAY_NIGHT) == date(2025, 9, 30)
    assert due_date("Master周末去书店", THURSDAY_NIGHT) == date(2025, 9, 28)
    assert due_date("Master下周末去书店", THURSDAY_NIGHT) == date(2025, 10, 5)
    assert due_date("Master月底发工资", THURSDAY_NIGHT) == date(2025, 9, 30)
    assert due_date("Master下个月底搬家", THURSDAY_NIGHT) == date(2025, 10, 31)
    assert due_date("Master下个月底搬家", _ts(2025, 12, 3, 12, 0)) == date(2026, 1, 31)


def test_latest_future_date_wins_and_past_or_missing_is_none() -> None:
    assert due_date("Master明天开始，下周三前做完", THURSDAY_NIGHT) == date(2025, 10, 1)
    assert due_date("Master昨天说要补卷子", THURSDAY_NIGHT) is None
    assert due_date("Master打算考华为认证", THURSDAY_NIGHT) is None
    assert due_date("Master明天回家", None) is None


def test_late_night_uses_previous_day() -> None:
    one_am_friday = _ts(2025, 9, 26, 1, 0)
    assert due_date("Master明天回老家", one_am_friday) == date(2025, 9, 26)
    assert due_date("Master周五交作业", one_am_friday) == date(2025, 9, 26)


def test_due_timestamp_is_end_of_due_day() -> None:
    assert due_timestamp("Master明天回老家", THURSDAY_NIGHT) == _ts(2025, 9, 26, 23, 59, 59)
    assert due_timestamp("Master打算学英语", THURSDAY_NIGHT) is None


def _plan(**fields: Any) -> dict[str, Any]:
    return {"kind": "plan", "status": "open", "occurred_from": THURSDAY_NIGHT, **fields}


def test_plan_state_expires_after_due_or_long_silence() -> None:
    due = _ts(2025, 9, 26, 23, 59, 59)
    assert plan_state(_plan(valid_to=due), due + (GRACE_DAYS - 1) * DAY) == "open"
    assert plan_state(_plan(valid_to=due), due + (GRACE_DAYS + 1) * DAY) == EXPIRED
    far = _ts(2025, 12, 31, 23, 59, 59)  # 到期日远：说了很久也不按「无到期日」过期
    assert plan_state(_plan(valid_to=far), THURSDAY_NIGHT + (NO_DUE_DAYS + 5) * DAY) == "open"
    assert plan_state(_plan(), THURSDAY_NIGHT + (NO_DUE_DAYS - 1) * DAY) == "open"
    assert plan_state(_plan(), THURSDAY_NIGHT + (NO_DUE_DAYS + 1) * DAY) == EXPIRED
    assert plan_state(_plan(status=None), THURSDAY_NIGHT) == "open"  # v8 没有 status


def test_plan_state_keeps_model_closures_and_ignores_other_kinds() -> None:
    late = THURSDAY_NIGHT + 400 * DAY
    assert plan_state(_plan(status="done"), late) == "done"
    assert plan_state(_plan(status="cancelled"), late) == "cancelled"
    assert plan_state({"kind": "fact", "occurred_from": THURSDAY_NIGHT}, late) == ""


def test_store_keeps_valid_to_and_patch_notes_leaves_text_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(paths, "notes_dir", lambda scope: tmp_path / scope / "notes_v2")
    store = NoteStore("aveline")
    drafts = [
        NoteDraft(
            kind="plan",
            text="Master明天回老家",
            source_event_ids=("e1",),
            metadata={"occurred_from": THURSDAY_NIGHT, "valid_to": 123.0},
        ),
        NoteDraft(kind="fact", text="Master在戒奶茶", source_event_ids=("e1",)),
    ]
    store.replace_segment(CONV, "seg", "v", drafts, segment_source_event_ids=("e1",))
    plan, fact = store.list_notes(CONV)
    assert plan["valid_to"] == 123.0 and fact["valid_to"] is None
    changed = store.patch_notes(
        CONV,
        lambda n: (
            {"valid_to": 456.0, "text": "改掉", "note_id": "x"} if n["kind"] == "fact" else None
        ),
    )
    fact_after = store.list_notes(CONV)[1]
    assert changed == 1 and fact_after["valid_to"] == 456.0
    assert fact_after["text"] == fact["text"] and fact_after["note_id"] == fact["note_id"]
    assert store.patch_notes(CONV, lambda n: {"valid_to": n["valid_to"]}) == 0


def test_extractor_writes_valid_to_for_plans_only() -> None:
    from memory.nightly.segment_jobs.episode import EpisodeExtractor
    from memory.nightly.segment_jobs.inputs import SegmentParams, build_conversation_inputs

    events = [
        {
            "event_id": "e0",
            "conversation_id": CONV,
            "role": "user",
            "content": "明晚之前写好创新点",
            "timestamp": THURSDAY_NIGHT,
            "message_id": "m0",
        },
        {
            "event_id": "e1",
            "conversation_id": CONV,
            "role": "assistant",
            "content": "加油",
            "timestamp": THURSDAY_NIGHT + 5,
            "message_id": "m0",
        },
    ]
    item = build_conversation_inputs(
        "aveline",
        CONV,
        events,
        params=SegmentParams(segmenter="v1"),
        now=THURSDAY_NIGHT + 10**6,
        tree_reader=lambda _cid: events,
    )[0]
    reply = json.dumps(
        {
            "topics": [{"ids": [0], "summary": "他说明晚之前写好创新点。"}],
            "facts": [
                {"ids": [0], "kind": "plan", "text": "Master明晚之前写好创新点"},
                {"ids": [0], "kind": "fact", "text": "Master明天要早起"},
            ],
        },
        ensure_ascii=False,
    )

    class _Scheduler:
        async def submit_llm_task(self, prompt: Any, **kwargs: Any) -> Any:
            yield reply

    extractor = EpisodeExtractor(
        scheduler_provider=_Scheduler,
        perspective_for_scope=lambda _s: {},
        persona_prefix_for_scope=lambda _s: "你是Aveline。",
    )
    notes = {n.kind: n for n in asyncio.run(extractor.extract(item)).notes}
    assert notes["plan"].metadata["valid_to"] == _ts(2025, 9, 26, 23, 59, 59)
    assert "valid_to" not in notes["fact"].metadata and "valid_to" not in notes["episode"].metadata


def _sel_plan(
    note_id: str, *, said: float, due: float | None = None, status: str = "open"
) -> dict[str, Any]:
    return {
        "note_id": note_id,
        "kind": "plan",
        "text": f"计划{note_id}",
        "status": status,
        "occurred_from": said,
        "occurred_to": said + 600,
        "valid_to": due,
    }


def test_pick_plans_drops_expired_and_keeps_old_plan_with_future_due() -> None:
    now = THURSDAY_NIGHT
    plans = [
        _sel_plan("past_due", said=now - 5 * DAY, due=now - 3 * DAY),
        _sel_plan("grace", said=now - 2 * DAY, due=now - 1 * DAY),
        _sel_plan("far_due", said=now - 20 * DAY, due=now + 10 * DAY),
        _sel_plan("old_no_due", said=now - 20 * DAY),
        _sel_plan("recent", said=now - 1 * DAY),
    ]
    assert [n["note_id"] for n in sel.pick_plans(plans, now)] == ["recent", "grace", "far_due"]


def test_backfill_fills_missing_due_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(paths, "notes_dir", lambda scope: tmp_path / scope / "notes_v2")
    store = NoteStore("aveline")
    drafts = [
        NoteDraft(
            kind="plan",
            text=text,
            source_event_ids=("e1",),
            metadata={"occurred_from": THURSDAY_NIGHT},
        )
        for text in ("Master明天（9月26日）回老家", "Master打算学英语")
    ]
    store.replace_segment(CONV, "seg", "v", drafts, segment_source_event_ids=("e1",))
    root = tmp_path / "aveline" / "notes_v2"
    now = THURSDAY_NIGHT + DAY
    preview = backfill_plan_due.run("aveline", apply=False, root=root, now=now)
    assert preview["plans"] == 2 and preview["would_fill"] == 1 and preview["state_open"] == 2
    assert all(n["valid_to"] is None for n in store.list_notes(CONV))
    monkeypatch.setattr(backfill_plan_due, "ROOT_DIR", tmp_path)  # 备份写到临时目录
    report = backfill_plan_due.run("aveline", apply=True, root=root, now=now)
    dues = {n["text"]: n["valid_to"] for n in store.list_notes(CONV)}
    assert report["filled"] == 1 and dues["Master明天（9月26日）回老家"] == _ts(
        2025, 9, 26, 23, 59, 59
    )
    assert dues["Master打算学英语"] is None
    assert "filled" not in backfill_plan_due.run("aveline", apply=True, root=root, now=now)
