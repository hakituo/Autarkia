"""决策 → 发送：发送方式协议、可带话题菜单、send plan，以及画像补齐移除 / planned_topic 可选。"""

from __future__ import annotations

import pytest

from core.services.active_care.agenda.send_plan import (
    OPENER_TYPE,
    build_send_plan,
    open_agenda_for_plan,
)
from core.services.active_care.agenda import get_active_agenda
from core.services.active_care.agenda.topics import build_topic_menu, format_topic_menu, topic_text
from core.services.active_care.decision.action_protocol import (
    decision_action_to_dict,
    parse_terminal_tool_call,
)
from core.services.active_care.decision.decision_output_parser import _normalize_decision_dict

RANKED = [
    {
        "id": "plan:a1",
        "title": "计划项：[14:45] 化学 · 氧化还原反应（化学）",
        "suggested_intent": "planned_topic",
        "reason": "plan_item",
    },
    {
        "id": "study:review_due",
        "title": "学习复习提醒：8个知识点到期",
        "suggested_intent": "planned_topic",
        "detail": "物理·恒定电流",
    },
    {"id": "urgent:tired", "title": "突发状态：tired", "suggested_intent": "bio_complaint"},
    {"id": "x:4", "title": "第四条", "suggested_intent": "share_thought"},
]


def _decision(style: str = "", topic_id: str = "") -> dict:
    return {"style": style, "topic_id": topic_id, "topic_menu": build_topic_menu(RANKED)}


# ── 协议 ──────────────────────────────────────────────


def test_tool_call_carries_style_and_topic():
    action = parse_terminal_tool_call(
        "send_active_care", {"reason_code": "plan", "style": "greeting", "topic_id": "plan:a1"}
    )
    out = decision_action_to_dict(action)
    assert out["style"] == "greeting" and out["topic_id"] == "plan:a1"


def test_unknown_style_falls_back_to_direct_and_defer_has_none():
    send = decision_action_to_dict(
        parse_terminal_tool_call("send_active_care", {"style": "shout"})
    )
    assert send["style"] == "direct"
    defer = decision_action_to_dict(
        parse_terminal_tool_call("defer_active_care", {"reason": "x", "style": "greeting"})
    )
    assert defer["style"] == "" and defer["topic_id"] == ""


def test_json_channel_keeps_style_and_topic():
    out = _normalize_decision_dict(
        {"action": "send_active_care", "style": "greeting", "topic_id": "plan:a1"}, "planned_topic"
    )
    assert out["style"] == "greeting" and out["topic_id"] == "plan:a1"


# ── 话题菜单 ──────────────────────────────────────────


def test_topic_menu_limits_and_strips_prefixes():
    menu = build_topic_menu(RANKED)
    assert [m["id"] for m in menu] == ["plan:a1", "study:review_due", "urgent:tired"]
    assert topic_text(menu[0]) == "[14:45] 化学 · 氧化还原反应（化学）"
    assert topic_text(menu[1]) == "8个知识点到期（物理·恒定电流）"
    assert "topic_id=plan:a1" in format_topic_menu(menu)
    assert format_topic_menu([]) == ""


# ── send plan ─────────────────────────────────────────


def test_greeting_without_topic_is_skipped():
    plan = build_send_plan(
        {"style": "greeting", "topic_menu": []}, intent="share_thought", specific_instruction=""
    )
    assert plan.skip_reason == "greeting_without_topic"


def test_greeting_uses_opener_and_dedups_recent_openers():
    plan = build_send_plan(
        _decision("greeting", "plan:a1"),
        intent="planned_topic",
        specific_instruction="原指令不应出现在开场白任务里",
        recent_opener_texts=["在不", "在干嘛"],
    )
    assert plan.sys_prompt_type == OPENER_TYPE and plan.is_opener
    assert plan.topic["id"] == "plan:a1"
    assert "在不、在干嘛" in plan.specific_instruction
    assert "原指令" not in plan.specific_instruction


def test_direct_planned_topic_passes_topic_text_not_trigger_literal():
    plan = build_send_plan(_decision("direct", "plan:a1"), intent="planned_topic", specific_instruction="")
    assert plan.sys_prompt_type == "planned_topic"
    assert plan.user_input_mock == "[14:45] 化学 · 氧化还原反应（化学）"


def test_direct_other_intent_appends_topic_to_instruction():
    plan = build_send_plan(
        _decision("direct", "urgent:tired"), intent="bio_complaint", specific_instruction="基础指引"
    )
    assert plan.user_input_mock == "[BIO_COMPLAINT_TRIGGER]"
    assert plan.specific_instruction == "基础指引\n本次要说的事：突发状态：tired"


def test_missing_topic_id_falls_back_to_menu_item_with_same_intent():
    plan = build_send_plan(_decision("greeting", ""), intent="planned_topic", specific_instruction="")
    assert plan.topic["id"] == "plan:a1"


@pytest.mark.asyncio
async def test_open_agenda_only_for_opener():
    opener = build_send_plan(_decision("greeting", "plan:a1"), intent="planned_topic", specific_instruction="")
    direct = build_send_plan(_decision("direct", "plan:a1"), intent="planned_topic", specific_instruction="")

    assert await open_agenda_for_plan("aveline", direct, intent="planned_topic", opener_text="x") is None
    await open_agenda_for_plan("aveline", opener, intent="planned_topic", opener_text="在不~")
    active = await get_active_agenda("aveline")
    assert active.opener == "在不~" and active.source_id == "plan:a1"
    assert active.topic == "[14:45] 化学 · 氧化还原反应（化学）"


# ── 画像补齐移除 / planned_topic 可选 ─────────────────


def test_priority_focus_no_longer_probes_portrait():
    from core.services.active_care.decision.priority_analyzer import PriorityAnalyzer
    from core.utils.time_utils import get_current_time

    snapshot = {"portrait_completeness": {"missing_items": ["wakeup", "meal", "activity"]}}
    focus = PriorityAnalyzer().build_priority_focus(
        snapshot, get_current_time().replace(hour=10), elapsed_seconds=7200
    )
    assert focus["portrait_priority"] == []
    assert focus["must_probe"] is False and focus["stage"] == "idle"


def test_candidates_have_no_portrait_or_companion_fallback(study_sandbox, agenda_sandbox):
    from core.services.active_care.decision.daily_push_priority import (
        build_daily_push_priority_candidates,
    )

    candidates = build_daily_push_priority_candidates(
        workspace_snapshot={},
        priority_focus={"portrait_priority": ["meal", "wakeup"]},
        urgent_needs=[],
    )
    ids = [c["id"] for c in candidates]
    assert not any(i.startswith("portrait:") for i in ids)
    assert "general:companion" not in ids


def test_planned_topic_available_only_with_plan_candidates():
    from core.services.active_care.decision.action_builder import build_available_actions

    def actions(focus):
        return build_available_actions(0.0, "neutral", False, 100.0, focus, False, {})

    assert "planned_topic" in actions({"has_planned_topic": True})
    assert "planned_topic" not in actions({})
    assert "user_health_reminder" not in actions({"portrait_priority": ["meal"]})


@pytest.mark.asyncio
async def test_silent_user_still_gets_rule_ranked_candidates(study_sandbox, agenda_sandbox):
    from core.services.active_care.decision.daily_push_priority import analyze_daily_push_priority
    from core.utils.time_utils import get_current_time

    now_dt = get_current_time()
    kwargs = dict(
        now=now_dt.timestamp(),
        now_dt=now_dt,
        latest_user_signal_ts=now_dt.timestamp() - 3 * 3600,
        workspace_snapshot={},
        priority_focus={},
        state_data={},
    )
    ranked = await analyze_daily_push_priority(urgent_needs=["tired"], **kwargs)
    assert ranked["enabled"] is True and ranked["analysis"]["source"] == "rule_silent"
    assert "urgent:tired" in [item["id"] for item in ranked["analysis"]["ranked"]]
