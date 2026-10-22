"""翻旧日记 · nightly 提示段与上下文格式化单测。

覆盖 ②（nightly 总结 prompt 的「前夜翻旧」段）：
- 四套日记 user 模板都带 {diary_reread_context} 占位符
- format_diary_reread_context 只收本人 scope 的 diary_reread 条目
- format_diary_context 排除 diary_reread（避免同段重复）
- build_daily_summary_messages 默认文案与自定义传入
以及 ③ 的深度纯函数 summary_read_depth_days。
"""
from __future__ import annotations

from datetime import date, datetime

from core.agents.chat_agent_components.persona_system.prompt.components import (
    GENERIC_DAILY_SUMMARY_USER_PROMPT_TEMPLATE,
    JOURNAL_DAILY_SUMMARY_USER_PROMPT_TEMPLATE,
    LING_DAILY_SUMMARY_USER_PROMPT_TEMPLATE,
    YE_DAILY_SUMMARY_USER_PROMPT_TEMPLATE,
)
from core.services.journal.diary_reread.policy import summary_read_depth_days
from core.services.journal.journal_helpers import (
    build_daily_summary_messages,
    format_diary_context,
    format_diary_reread_context,
)
from core.services.journal.models import JournalEntry

_ALL_TEMPLATES = (
    ("aveline", JOURNAL_DAILY_SUMMARY_USER_PROMPT_TEMPLATE),
    ("ling", LING_DAILY_SUMMARY_USER_PROMPT_TEMPLATE),
    ("ye", YE_DAILY_SUMMARY_USER_PROMPT_TEMPLATE),
    ("generic", GENERIC_DAILY_SUMMARY_USER_PROMPT_TEMPLATE),
)


def _entry(
    *,
    source: str = "aveline",
    entry_type: str = "proactive",
    content: str = "片段",
    thought: str | None = None,
) -> JournalEntry:
    return JournalEntry(
        timestamp=1791781620.0,
        time_str="23:47:00",
        type=entry_type,
        content=content,
        thought=thought,
        source=source,
    )


def _messages(persona: str, reread_context: str = "") -> str:
    return build_daily_summary_messages(
        date_str="2026-10-12",
        diary_context="随手记片段",
        chat_context="聊天",
        active_care_context="主动关怀",
        user_status_summary="状态",
        study_context="学习",
        daily_context="生活画像",
        persona=persona,
        diary_reread_context=reread_context,
    )[1]["content"]


# ── 模板占位符 ─────────────────────────────────────────────


def test_all_templates_carry_reread_placeholder():
    for label, template in _ALL_TEMPLATES:
        assert "{diary_reread_context}" in template, f"{label} 模板缺少翻旧段占位符"
        # 翻旧段必须紧跟随手记段之后
        assert template.index("{diary_reread_context}") > template.index("{diary_context}")


def test_all_personas_build_without_key_error():
    for label, _ in _ALL_TEMPLATES:
        content = _messages(label, reread_context="[23:47] 睡不着，翻了翻之前的日记。")
        assert "前夜翻看旧日记的记录" in content
        assert "睡不着，翻了翻之前的日记。" in content


def test_generic_persona_also_formats():
    # 未注册专属模板的角色走 generic 分支（内部会 warning，属预期）
    content = _messages("some_unregistered_role")
    assert "前夜没有翻看旧日记。" in content


# ── 上下文格式化 ───────────────────────────────────────────


def test_format_diary_reread_context_only_own_scope():
    entries = [
        _entry(entry_type="diary_reread", content="睡不着，翻了翻之前的日记。"),
        _entry(source="ling", entry_type="diary_reread", content="Ling翻的"),
        _entry(entry_type="proactive", content="普通随手记"),
    ]
    text = format_diary_reread_context(entries, persona="aveline")
    assert "睡不着" in text
    assert "Ling翻的" not in text
    assert "普通随手记" not in text


def test_format_diary_reread_context_empty():
    assert format_diary_reread_context([], persona="aveline") == ""


def test_format_diary_context_excludes_reread():
    entries = [
        _entry(entry_type="proactive", content="普通随手记"),
        _entry(entry_type="diary_reread", content="翻旧记录不应出现在随手记段"),
    ]
    text = format_diary_context(entries, persona="aveline")
    assert "普通随手记" in text
    assert "翻旧记录不应出现" not in text


def test_build_messages_default_reread_text():
    content = _messages("aveline")
    assert "前夜没有翻看旧日记。" in content
    assert "我前夜翻看旧日记的记录" in content


# ── ③ 读取总结的深度纯函数 ─────────────────────────────────


def test_summary_read_depth_days():
    anchor = date(2026, 10, 12)
    assert summary_read_depth_days(anchor, date(2026, 10, 12)) == 0  # 当天
    assert summary_read_depth_days(anchor, date(2026, 10, 11)) == 1
    assert summary_read_depth_days(anchor, date(2026, 9, 30)) == 12
    assert summary_read_depth_days(anchor, date(2026, 1, 31)) > 250
    assert summary_read_depth_days(anchor, date(2026, 10, 13)) == 0  # 未来钳 0


def test_summary_read_depth_days_tolerates_bad_input():
    assert summary_read_depth_days(None, None) == 0
    assert summary_read_depth_days(datetime(2026, 10, 12), None) == 0
