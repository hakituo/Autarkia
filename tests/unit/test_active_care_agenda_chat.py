"""开场议程在主聊天侧：议程注入、分阶段引导、close_agenda 工具、开场白生成 prompt。"""

from __future__ import annotations

import pytest

from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
    build_agenda_chat_injection,
)
from core.agents.chat_agent_components.streaming_pipeline import agenda_injections as ai
from core.agents.chat_agent_components.streaming_pipeline.agenda_probes import (
    _probe_active_care_agenda,
)
from core.services.active_care import agenda as ag
from core.tools.close_agenda_tool import CloseAgendaTool, close_agenda_tool_names


async def _open(topic: str = "化学 · 氧化还原反应") -> ag.Agenda:
    return await ag.open_agenda("aveline", ag.Agenda(topic=topic, opener="在不"))


# ── 注入文本按轮数推进 ────────────────────────────────


def test_injection_stages_follow_turns():
    first = build_agenda_chat_injection(opener="在不", topic="化学复习", turn=1)
    bridge = build_agenda_chat_injection(opener="在不", topic="化学复习", turn=3)
    late = build_agenda_chat_injection(opener="在不", topic="化学复习", turn=6)

    assert "化学复习" in first and "「在不」" in first
    assert "不要提这件事" in first
    assert "自然的切口" in bridge and "不要提这件事" not in bridge
    assert "轻轻带一句" in late
    assert all("close_agenda" in text for text in (first, bridge, late))


# ── 议程探针 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_probe_injects_in_private_chat_and_commit_counts_turn():
    opened = await _open()

    text, commit = await _probe_active_care_agenda({"user_id": "web_role_aveline"})
    assert "化学 · 氧化还原反应" in text and "第 1 轮" in text
    await commit()
    text2, _ = await _probe_active_care_agenda({"user_id": "shared__persona__core_aveline"})
    assert "第 2 轮" in text2
    assert (await ag.get_active_agenda("aveline")).agenda_id == opened.agenda_id


@pytest.mark.asyncio
async def test_probe_skips_group_peer_and_empty():
    assert await _probe_active_care_agenda({"user_id": "web_role_aveline"}) == ("", None)
    await _open()
    assert await _probe_active_care_agenda({"user_id": "group_1_2__persona__core_aveline"}) == ("", None)
    assert await _probe_active_care_agenda({"user_id": "peer_aveline_ling"}) == ("", None)
    assert await _probe_active_care_agenda({"user_id": "web_role_ling"}) == ("", None)


def test_agenda_sits_right_after_plan_reminder():
    names = list(ai.AGENDA_PRIORITY)
    assert names.index("active_care_agenda") == names.index("plan_reminder") + 1
    item = next(i for i in ai._LADDER if i.name == "active_care_agenda")
    assert item.once_per_day is False and item.chitchat_gated is False


# ── close_agenda 工具 ─────────────────────────────────


@pytest.mark.asyncio
async def test_tool_is_offered_only_while_agenda_is_open():
    assert await close_agenda_tool_names("web_role_aveline") == []
    await _open()
    assert await close_agenda_tool_names("web_role_aveline") == ["close_agenda"]
    assert await close_agenda_tool_names("group_1_2__persona__core_aveline") == []


@pytest.mark.asyncio
async def test_tool_closes_agenda():
    await _open()
    tool = CloseAgendaTool()
    tool.set_runtime_context({"user_id": "web_role_aveline"})

    first = await tool._run(reason="doing")
    second = await tool._run(reason="done")

    assert "已结束" in first and "不需要调用" in second
    assert await ag.get_active_agenda("aveline") is None
    assert await close_agenda_tool_names("web_role_aveline") == []


def test_tool_is_registered_in_active_care_domain():
    from core.tools.tool_metadata import get_tool_domain

    assert get_tool_domain("close_agenda") == "active_care"


# ── 开场白生成 prompt ─────────────────────────────────


def test_opener_task_block_and_filters():
    from core.services.active_care.prompt.sections.constraints import (
        _build_no_interrogation_constraint,
    )
    from core.services.active_care.prompt.sections.filtering import _filter_dynamic_sections
    from core.services.active_care.prompt.sections.models import PromptSection
    from core.services.active_care.prompt.sections.tasks import _build_task_block_dynamic

    block = _build_task_block_dynamic(
        "agenda_opener", "15:00", "[AGENDA_OPENER_TRIGGER]", None, None,
        specific_instruction="- 最近用过这些开场，这次换一个不同的说法：在不\n",
    )
    assert "轻问候开场" in block and "换一个不同的说法：在不" in block
    assert _build_no_interrogation_constraint("agenda_opener") == ""

    sections = [
        PromptSection("tone_reference_text", "语气"),
        PromptSection("today_plan", "今日计划"),
        PromptSection("context_guard", "上下文"),
        PromptSection("task_block_dynamic", block),
    ]
    kept = {s.name for s in _filter_dynamic_sections("agenda_opener", sections)}
    assert kept == {"tone_reference_text", "task_block_dynamic"}


def test_opener_counts_as_question_for_cadence():
    from core.services.active_care.cadence.cadence_guard import QUESTION_INTENTS

    assert "agenda_opener" in QUESTION_INTENTS
