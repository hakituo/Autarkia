"""开场议程存储：开 / 读 / 计轮 / 结束 / 过期 / 替换 / 最近开场白。

文件已由 conftest 的 ``_isolate_active_care_agenda`` 指到临时目录；时间一律显式传入。
"""

from __future__ import annotations

import pytest

from core.services.active_care import agenda as ag
from core.services.active_care.agenda import paths

NOW = 1_800_000_000.0


def _agenda(topic: str = "化学 · 氧化还原反应", opener: str = "在不") -> ag.Agenda:
    return ag.Agenda(topic=topic, opener=opener, source_id="plan:x", created_ts=NOW)


@pytest.mark.asyncio
async def test_open_then_read_and_count_turns():
    opened = await ag.open_agenda("aveline", _agenda(), now=NOW)

    active = await ag.get_active_agenda("aveline", now=NOW + 60)
    assert active is not None and active.topic == "化学 · 氧化还原反应"
    assert active.turns == 0
    assert await ag.record_agenda_turn("aveline", opened.agenda_id) == 1
    assert await ag.record_agenda_turn("aveline", opened.agenda_id) == 2
    assert (await ag.get_active_agenda("aveline", now=NOW + 120)).turns == 2


@pytest.mark.asyncio
async def test_close_clears_active_and_archives():
    await ag.open_agenda("aveline", _agenda(), now=NOW)

    closed = await ag.close_agenda("aveline", "doing", now=NOW + 300)

    assert closed is not None and closed.topic == "化学 · 氧化还原反应"
    assert await ag.get_active_agenda("aveline", now=NOW + 301) is None
    assert await ag.close_agenda("aveline", "done", now=NOW + 302) is None
    data = paths.agenda_file("aveline").read_text(encoding="utf-8")
    assert '"closed_reason": "doing"' in data


@pytest.mark.asyncio
async def test_expired_agenda_is_dropped():
    await ag.open_agenda("aveline", _agenda(), now=NOW)

    assert await ag.get_active_agenda("aveline", now=NOW + ag.MAX_AGE_SECONDS - 1) is not None
    assert await ag.get_active_agenda("aveline", now=NOW + ag.MAX_AGE_SECONDS) is None
    assert '"closed_reason": "expired"' in paths.agenda_file("aveline").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_new_agenda_replaces_old_and_stale_turn_is_ignored():
    first = await ag.open_agenda("aveline", _agenda("旧话题", "在吗"), now=NOW)
    await ag.open_agenda("aveline", _agenda("新话题", "在干嘛"), now=NOW + 10)

    assert (await ag.get_active_agenda("aveline", now=NOW + 20)).topic == "新话题"
    # 旧议程的提交晚到：不能把轮数记到新议程上
    assert await ag.record_agenda_turn("aveline", first.agenda_id) == -1
    assert await ag.recent_openers("aveline") == ["在干嘛", "在吗"]


@pytest.mark.asyncio
async def test_scopes_are_independent():
    await ag.open_agenda("aveline", _agenda(), now=NOW)

    assert await ag.get_active_agenda("ling", now=NOW) is None


def test_scope_and_private_conversation_rules():
    assert ag.scope_for_conversation("web_role_aveline") == "aveline"
    assert ag.scope_for_conversation("shared__persona__core_aveline") == "aveline"
    assert ag.is_agenda_conversation("web_role_aveline")
    assert ag.is_agenda_conversation("private_123__persona__core_aveline")
    assert not ag.is_agenda_conversation("group_1_2__persona__core_aveline")
    assert not ag.is_agenda_conversation("peer_aveline_ling")
    assert not ag.is_agenda_conversation("default_user__circle__ling")
    assert not ag.is_agenda_conversation("")
