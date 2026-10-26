"""`JournalSummaryService.distill_memory` 的回归测试。

覆盖重点：LLM 返回空内容时不能把已蒸好的记忆清成只剩标题
（Windows 侧就因此把 2026-09 的蒸馏记忆写成了 28 字节空文件）。
"""

import asyncio
from datetime import datetime
from unittest.mock import MagicMock

from core.services.journal.models import MonthlySummary
from core.services.journal.summary_service import JournalSummaryService


def _make_service() -> JournalSummaryService:
    journal = MagicMock()
    journal.storage = MagicMock()
    journal.settings = MagicMock()
    return JournalSummaryService(journal)


def _patch_common(monkeypatch, tmp_path, stream):
    monkeypatch.setattr("core.utils.common.get_project_root", lambda: tmp_path)
    monkeypatch.setattr("core.services.journal.summary_service.call_llm_stream", stream)


_PROFILE_REL = ("core", "character", "configs", "extra")


def _profile_path(tmp_path, year: str, month: str):
    return tmp_path.joinpath(*_PROFILE_REL, year, month, "distilled_profile.md")


def test_distill_memory_keeps_existing_file_when_llm_returns_empty(tmp_path, monkeypatch):
    """LLM 返回空内容时，已有的蒸馏记忆必须原样保留。"""
    service = _make_service()
    target = _profile_path(tmp_path, "2026", "09")
    target.parent.mkdir(parents=True)
    original = "# 2026-09 Distilled Memory\n\n### 用户核心特征更新\n- 作息长期昼夜颠倒\n"
    target.write_text(original, encoding="utf-8")

    async def _empty_stream(*_args, **_kwargs):
        return ""

    _patch_common(monkeypatch, tmp_path, _empty_stream)

    summary = MonthlySummary(month="2026-09", summary="本月总结", mood_trend="平稳")
    asyncio.run(service.distill_memory(summary, datetime(2026, 9, 30, 12, 0)))

    assert target.read_text(encoding="utf-8") == original


def test_distill_memory_writes_new_content_when_available(tmp_path, monkeypatch):
    """有蒸馏内容时正常写入。"""
    service = _make_service()

    async def _ok_stream(*_args, **_kwargs):
        return "### 用户核心特征更新\n- 作息长期昼夜颠倒\n"

    _patch_common(monkeypatch, tmp_path, _ok_stream)

    summary = MonthlySummary(month="2026-10", summary="本月总结", mood_trend="平稳")
    asyncio.run(service.distill_memory(summary, datetime(2026, 10, 13, 12, 0)))

    target = _profile_path(tmp_path, "2026", "10")
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert content.startswith("# 2026-10 Distilled Memory")
    assert "作息长期昼夜颠倒" in content
