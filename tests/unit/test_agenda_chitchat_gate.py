"""议程闲聊门控 + 当日状态持久化的守卫测试（2026-10-02 新增）。

背景：once_per_day 只解决了「同一件事重复催」，没解决「每天必催一次」——
主人随口聊两句照样会被塞一条催办。现在的口径是**聊天就是聊天**：
带 chitchat_gated 的条目要连续纯闲聊攒够 CHITCHAT_TURNS_BEFORE_AGENDA 轮才允许出场，
催过一次计数归零；没攒够就什么都不注入。

优先级竞争本身在 ``test_agenda_injections.py``。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.agents.chat_agent_components.streaming_pipeline import agenda_injections as ai
from core.agents.chat_agent_components.streaming_pipeline import agenda_state as ast


@pytest.fixture(autouse=True)
def _isolate(agenda_sandbox):
    """本文件所有用例都隔离议程状态文件，绝不写进真实 companion_data。"""
    return agenda_sandbox


def _today() -> str:
    from core.utils.time_utils import now_str

    return now_str("%Y-%m-%d")


def _set_streak(user_id: str, value: int) -> None:
    state = ast._read_state(user_id, _today())
    state["chitchat_streak"] = value
    ast._write_state(user_id, _today(), state)


def _ladder_with(once: set[str], gated: set[str] | None = None):
    """复制当前阶梯，把名字在 once/gated 里的条目分别标上对应标记。"""
    gated = gated or set()
    return tuple(
        ai.AgendaItem(item.name, item.probe, item.name in once, item.name in gated, item.level)
        for item in ai._LADDER
    )


@pytest.mark.asyncio
async def test_chitchat_gated_agenda_stays_silent_before_threshold(fake_agenda_ladder):
    """没聊够轮数：门关着，一条催办都不许出场 —— 回复里只剩正常聊天。

    注意「门关着」只挡 chitchat_gated 的条目，不门控的（如 P1）照常探测，
    所以这里断言的是 today_plan 没被碰过，而不是整个阶梯没动。
    """
    calls, _commits = fake_agenda_ladder(hits={"today_plan": "【今日计划】x"})
    with patch.object(ai, "_LADDER", _ladder_with({"today_plan"}, {"today_plan"})):
        name, text, commit = await ai.pick_agenda_injection(agent=None, user_id="u1")

    assert (name, text, commit) == ("", "", None)
    assert "today_plan" not in calls, "门关着时不该探测被门控的条目"


@pytest.mark.asyncio
async def test_chitchat_gate_opens_at_threshold(fake_agenda_ladder):
    """攒够 CHITCHAT_TURNS_BEFORE_AGENDA 轮纯闲聊后，才允许放一条出来。"""
    fake_agenda_ladder(hits={"today_plan": "【今日计划】x"})
    ladder = _ladder_with({"today_plan"}, {"today_plan"})

    # 差一轮：仍然沉默
    _set_streak("u1", ai.CHITCHAT_TURNS_BEFORE_AGENDA - 1)
    with patch.object(ai, "_LADDER", ladder):
        assert (await ai.pick_agenda_injection(agent=None, user_id="u1"))[0] == ""

    # 刚好到阈值：放行
    _set_streak("u1", ai.CHITCHAT_TURNS_BEFORE_AGENDA)
    with patch.object(ai, "_LADDER", ladder):
        name, text, commit = await ai.pick_agenda_injection(agent=None, user_id="u1")
    assert name == "today_plan"
    assert text == "【今日计划】x"
    await commit()


@pytest.mark.asyncio
async def test_pure_chat_turn_bumps_streak(fake_agenda_ladder):
    """本轮什么都没注入 = 纯聊天一轮，计数 +1。"""
    fake_agenda_ladder(hits={})
    with patch.object(ai, "_LADDER", _ladder_with(set(), {"today_plan"})):
        assert ast._get_chitchat_streak("u1", _today()) == 0
        for expected in (1, 2, 3):
            await ai.pick_agenda_injection(agent=None, user_id="u1")
            assert ast._get_chitchat_streak("u1", _today()) == expected


@pytest.mark.asyncio
async def test_commit_resets_streak(fake_agenda_ladder):
    """真的催过一次 → 计数归零，重新开始数；否则门一直开着退回老毛病。"""
    fake_agenda_ladder(hits={"today_plan": "x"})
    _set_streak("u1", ai.CHITCHAT_TURNS_BEFORE_AGENDA)
    with patch.object(ai, "_LADDER", _ladder_with({"today_plan"}, {"today_plan"})):
        _name, _text, commit = await ai.pick_agenda_injection(agent=None, user_id="u1")
        assert ast._get_chitchat_streak("u1", _today()) == ai.CHITCHAT_TURNS_BEFORE_AGENDA
        await commit()
    assert ast._get_chitchat_streak("u1", _today()) == 0


@pytest.mark.asyncio
async def test_ungated_agenda_bypasses_closed_gate(fake_agenda_ladder):
    """不门控的条目（P1 计划提醒，带 300s TTL）门关着也要放行，否则会过期丢掉。"""
    _calls, _commits = fake_agenda_ladder(hits={"plan_reminder": "【计划提醒】x"})
    # 除 P1 外全部门控，且计数为 0（门关）—— P1 仍应出场
    gated = {"daily_study_task", "tomorrow_tone", "today_plan", "meal_care"}
    assert ast._get_chitchat_streak("u1", _today()) == 0
    with patch.object(ai, "_LADDER", _ladder_with(set(), gated)):
        name, _t, commit = await ai.pick_agenda_injection(agent=None, user_id="u1")
        assert name == "plan_reminder"
        await commit()


# ────────────────────── 状态持久化 ──────────────────────


def test_legacy_marker_format_is_read_compatible(agenda_sandbox):
    """2026-10-02 之前的标记文件值是「已注入名单列表」，升级后必须还能读。"""
    import json

    path = ast._marker_path("u1", _today())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"u1": ["today_plan"]}), encoding="utf-8")

    assert ast._already_injected("u1", "today_plan", _today()) is True
    assert ast._already_injected("u1", "meal_care", _today()) is False
    assert ast._get_chitchat_streak("u1", _today()) == 0

    # 旧文件上写新状态时，已注入名单不能丢
    ast._bump_chitchat_streak("u1", _today())
    assert ast._already_injected("u1", "today_plan", _today()) is True
    assert ast._get_chitchat_streak("u1", _today()) == 1


def test_streak_state_is_per_user(agenda_sandbox):
    """门控计数也按会话隔离，别把 A 会话的闲聊算到 B 头上。"""
    _set_streak("u1", 7)
    assert ast._get_chitchat_streak("u1", _today()) == 7
    assert ast._get_chitchat_streak("u2", _today()) == 0


def test_safe_int_rejects_dirty_and_bool():
    assert ast._safe_int(None) == 0
    assert ast._safe_int("abc") == 0
    assert ast._safe_int(True) == 0
    assert ast._safe_int(-5) == 0
    assert ast._safe_int("4") == 4
