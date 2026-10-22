# -*- coding: utf-8 -*-
"""验证「确认型回忆提问」意图闸门真实生效。

验证项：
1. 确认型提问（「你还记得这个吗」）命中时，两个记忆工具都只回存在性
   信号，命中正文不出现在工具返回里；
2. 内容型提问（「叫什么」）正常返回正文；
3. 确认型但无命中时照旧回「未找到」，不会诱导角色瞎说记得；
4. 意图判定的纯函数边界案例（含追问词的句子不被误杀）。

运行：venv_cpu\\Scripts\\python.exe tests\\scripts\\tools\\verify_recall_intent_gate.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core.tools.recall_intent import is_confirmation_only_recall  # noqa: E402
from core.tools.search_chat_history_tool import SearchChatHistoryTool  # noqa: E402
from core.tools.search_memory_tool import SearchMemoryTool  # noqa: E402

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


def _memory_item() -> dict:
    return {"summary": _SECRET, "content": _SECRET, "timestamp": 0, "category": "daily"}


def _chat_event() -> dict:
    return {
        "role": "user",
        "content": _SECRET,
        "created_at": "2026-09-01 10:00:00",
        "timestamp": 1,
        "event_type": "chat_message",
    }


async def _main() -> None:
    # 1. search_memory 确认型：隐藏正文
    mem_tool = SearchMemoryTool()
    mem_tool.set_runtime_context(
        {"agent": _FakeAgent([_memory_item()]), "user_id": "u1", "last_user_text": "你还记得这个吗"}
    )
    reply = await mem_tool._run(query="校园超市", include_chat_history=False)  # noqa: SLF001
    assert "内容已隐藏" in reply and _SECRET not in reply, reply
    print("[PASS] search_memory 确认型提问只回存在性信号，正文已隐藏")

    # 2. search_memory 内容型：返回正文
    mem_tool.set_runtime_context(
        {
            "agent": _FakeAgent([_memory_item()]),
            "user_id": "u1",
            "last_user_text": "你还记得我们当时买了什么吗",
        }
    )
    reply = await mem_tool._run(query="校园超市", include_chat_history=False)  # noqa: SLF001
    assert _SECRET in reply, reply
    print("[PASS] search_memory 内容型提问正常返回正文")

    # 3. search_chat_history 确认型
    chat_tool = SearchChatHistoryTool()
    chat_tool._search_in_store = lambda **kwargs: [_chat_event()]  # noqa: SLF001
    chat_tool.set_runtime_context(
        {"agent": object(), "user_id": "u1", "last_user_text": "还记得这个吗"}
    )
    reply = await chat_tool._run(query="校园超市")
    assert "内容已隐藏" in reply and _SECRET not in reply, reply
    print("[PASS] search_chat_history 确认型提问只回存在性信号，正文已隐藏")

    # 4. search_chat_history 无聊天命中、走记忆回退，确认型同样隐藏
    fallback_tool = SearchChatHistoryTool()
    fallback_tool._search_in_store = lambda **kwargs: []  # noqa: SLF001
    fallback_tool.set_runtime_context(
        {"agent": _FakeAgent([_memory_item()]), "user_id": "u1", "last_user_text": "你还记得吗"}
    )
    reply = await fallback_tool._run(query="校园超市")
    assert "内容已隐藏" in reply and _SECRET not in reply, reply
    print("[PASS] search_chat_history 记忆回退路径在确认型提问下同样隐藏正文")

    # 5. 无命中不瞎说
    empty_tool = SearchMemoryTool()
    empty_tool.set_runtime_context(
        {"agent": _FakeAgent([]), "user_id": "u1", "last_user_text": "你还记得这个吗"}
    )
    reply = await empty_tool._run(query="不存在", include_chat_history=False)  # noqa: SLF001
    assert "未找到" in reply and "内容已隐藏" not in reply, reply
    print("[PASS] 确认型提问但无命中时照旧返回未找到")

    # 6. 判定边界
    assert is_confirmation_only_recall("记不记得我们的约定")
    assert is_confirmation_only_recall("没忘吧")
    assert not is_confirmation_only_recall("还记得那家店叫什么吗")
    assert not is_confirmation_only_recall("还记得吗，后来怎么了")
    assert not is_confirmation_only_recall("记得帮我带瓶水")
    print("[PASS] 意图判定边界案例符合预期")


if __name__ == "__main__":
    asyncio.run(_main())
    print("\n全部验证通过。")
