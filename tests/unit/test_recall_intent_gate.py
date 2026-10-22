# -*- coding: utf-8 -*-
"""「确认型回忆提问」意图闸门的单测。

覆盖：
1. ``is_confirmation_only_recall`` 的保守判定（确认型收敛、内容型放行）；
2. search_memory 工具在确认型提问时只回存在性信号、正文不泄露；
3. search_chat_history 工具在确认型提问（含记忆回退路径）时同样收敛。
"""
from __future__ import annotations

import pytest

from core.tools.recall_intent import (
    CONTENT_USAGE_NOTE,
    build_confirmation_reply,
    is_confirmation_only_recall,
)
from core.tools.search_chat_history_tool import SearchChatHistoryTool
from core.tools.search_memory_tool import SearchMemoryTool

# ----------------------------------------------------------------------
# 意图判定（纯函数）
# ----------------------------------------------------------------------

CONFIRM_CASES = [
    "你还记得这个吗",
    "还记得吗",
    "你还记得我们上次去的那家店吗？",
    "记得不？",
    "没忘吧",
    "能想起来吗",
    "记不记得我们的约定",
    "你还记得这个",  # 强线索「还记得」，不依赖句尾助词
]

CONTENT_CASES = [
    "你还记得那家店叫什么吗",  # 含「什么」
    "还记得他后来怎么样了吗",  # 含「怎么/后来」
    "你记得她生日是几号",  # 含「几」
    "还记得吗，后来怎么了",  # 先确认后追问，按内容型
    "还记得当时的经过吗",  # 含「经过」
    "记得帮我下班带瓶水",  # 祈使句，不是回忆提问
    "今天天气怎么样",  # 无回忆线索
    "",
]


@pytest.mark.parametrize("message", CONFIRM_CASES)
def test_确认型提问被识别(message: str) -> None:
    assert is_confirmation_only_recall(message) is True


@pytest.mark.parametrize("message", CONTENT_CASES)
def test_内容型与非回忆提问不被误杀(message: str) -> None:
    assert is_confirmation_only_recall(message) is False


def test_确认型回复只含数量不含正文() -> None:
    reply = build_confirmation_reply(memory_count=2, chat_count=1)
    assert "3 条" in reply
    assert "记忆 2 条" in reply
    assert "聊天 1 条" in reply
    assert "内容已隐藏" in reply


# ----------------------------------------------------------------------
# 工具层闸门
# ----------------------------------------------------------------------

_SECRET = "那天在校园超市一起买了关东煮"


class _FakeMemoryManager:
    def __init__(self, items: list[dict]) -> None:
        self._items = items

    def hybrid_search(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self._items


class _FakeAgent:
    def __init__(self, items: list[dict] | None = None) -> None:
        self._mm = _FakeMemoryManager(items or [])

    async def get_memory_manager_async(self, user_id):  # noqa: ANN001
        return self._mm

    def _get_memory_manager(self, user_id):  # noqa: ANN001
        return self._mm


def _one_memory() -> dict:
    return {"summary": _SECRET, "content": _SECRET, "timestamp": 0, "category": "daily"}


async def test_search_memory_确认型只回存在性信号() -> None:
    tool = SearchMemoryTool()
    tool.set_runtime_context(
        {"agent": _FakeAgent([_one_memory()]), "user_id": "u1", "last_user_text": "你还记得这个吗"}
    )
    reply = await tool._run(query="校园超市", include_chat_history=False)  # noqa: SLF001

    assert "内容已隐藏" in reply
    assert _SECRET not in reply


async def test_search_memory_内容型正常返回正文并带使用提示() -> None:
    tool = SearchMemoryTool()
    tool.set_runtime_context(
        {
            "agent": _FakeAgent([_one_memory()]),
            "user_id": "u1",
            "last_user_text": "你还记得我们当时在超市买了什么吗",
        }
    )
    reply = await tool._run(query="校园超市", include_chat_history=False)  # noqa: SLF001

    assert _SECRET in reply
    assert CONTENT_USAGE_NOTE in reply


async def test_search_memory_无命中时不撒谎提示记得() -> None:
    tool = SearchMemoryTool()
    tool.set_runtime_context(
        {"agent": _FakeAgent([]), "user_id": "u1", "last_user_text": "你还记得这个吗"}
    )
    reply = await tool._run(query="不存在的事", include_chat_history=False)  # noqa: SLF001

    assert "未找到" in reply
    assert "内容已隐藏" not in reply


async def test_search_chat_history_确认型隐藏正文() -> None:
    tool = SearchChatHistoryTool()
    tool._search_in_store = lambda **kwargs: [  # noqa: SLF001
        {
            "role": "user",
            "content": _SECRET,
            "created_at": "2026-09-01 10:00:00",
            "timestamp": 1,
            "event_type": "chat_message",
        }
    ]
    tool.set_runtime_context(
        {"agent": object(), "user_id": "u1", "last_user_text": "还记得这个吗"}
    )

    reply = await tool._run(query="校园超市")

    assert "内容已隐藏" in reply
    assert _SECRET not in reply


async def test_search_chat_history_内容型正常返回() -> None:
    tool = SearchChatHistoryTool()
    tool._search_in_store = lambda **kwargs: [  # noqa: SLF001
        {
            "role": "user",
            "content": _SECRET,
            "created_at": "2026-09-01 10:00:00",
            "timestamp": 1,
            "event_type": "chat_message",
        }
    ]
    tool.set_runtime_context(
        {"agent": object(), "user_id": "u1", "last_user_text": "我们当时买了什么来着"}
    )

    reply = await tool._run(query="校园超市")

    assert _SECRET in reply
    assert CONTENT_USAGE_NOTE in reply


async def test_search_chat_history_记忆回退路径确认型同样隐藏() -> None:
    tool = SearchChatHistoryTool()
    tool._search_in_store = lambda **kwargs: []  # noqa: SLF001
    tool.set_runtime_context(
        {"agent": _FakeAgent([_one_memory()]), "user_id": "u1", "last_user_text": "你还记得吗"}
    )

    reply = await tool._run(query="校园超市")

    assert "内容已隐藏" in reply
    assert _SECRET not in reply
