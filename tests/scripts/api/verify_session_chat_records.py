"""验证会话真实聊天记录端点：心想归一化 + 摘要过滤 + 排序。

背景：安卓记忆页的聊天记录树原先取的是记忆库（``/history``），既稀疏又混进
【历史摘要】与非对话条目；现改为取 ``chat_history`` 事件流（
``memory.core.history_ops.get_conversation_records``）。本脚本用临时
``ChatHistoryStore`` 造出两种心想形态，验证归一化与过滤结果。

运行：venv_cpu/Scripts/python.exe tests/scripts/api/verify_session_chat_records.py
"""

import asyncio
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.services.chat_history_store import ChatHistoryStore  # noqa: E402
from memory.core.history_ops import get_conversation_records  # noqa: E402

CONVERSATION_ID = "verify_records_session"


def _seed(store: ChatHistoryStore) -> list[dict]:
    """写入两种心想形态 + 摘要 + 一条无关 system 事件。"""
    return store.append_events(
        [
            {
                "conversation_id": CONVERSATION_ID,
                "role": "user",
                "content": "今天心情还不错",
                "message_id": "m1",
                "now_dt": datetime.fromtimestamp(1000.0),
            },
            {
                "conversation_id": CONVERSATION_ID,
                "role": "assistant",
                "content": "那就好呀",
                "message_id": "m1",
                "now_dt": datetime.fromtimestamp(1000.0),
            },
            {
                # 普通聊天的心想：独立事件，与对话事件共享 message_id
                "conversation_id": CONVERSATION_ID,
                "role": "system",
                "content": "她其实是在试探我",
                "message_id": "m1",
                "event_type": "chat_thought",
                "metadata": {"hidden": True},
                "now_dt": datetime.fromtimestamp(1001.0),
            },
            {
                # 主动消息的心想：嵌在正文开头
                "conversation_id": CONVERSATION_ID,
                "role": "assistant",
                "content": "（心想：该提醒她吃药了）\n\n记得吃药哦",
                "message_id": "m2",
                "event_type": "proactive_message",
                "now_dt": datetime.fromtimestamp(2000.0),
            },
            {
                "conversation_id": CONVERSATION_ID,
                "role": "assistant",
                "content": "【历史摘要】前情提要：这是上下文压缩产物",
                "message_id": "m3",
                "now_dt": datetime.fromtimestamp(3000.0),
            },
            {
                "conversation_id": CONVERSATION_ID,
                "role": "system",
                "content": "不该出现在聊天记录里的系统事件",
                "message_id": "m4",
                "event_type": "internal_note",
                "now_dt": datetime.fromtimestamp(4000.0),
            },
        ]
    )


def _check_records(refs: list[dict]) -> None:
    records = asyncio.run(get_conversation_records(conversation_id=CONVERSATION_ID))
    assert len(records) == 3, f"应只剩 3 条对话，实际 {len(records)}: {records}"

    user_entry, reply_entry, proactive_entry = records
    assert user_entry["role"] == "user" and user_entry["content"] == "今天心情还不错"
    assert "thought" not in user_entry, "心想不能挂到 user 一侧"
    assert user_entry["id"] == refs[0]["event_id"], "id 应为 event_id"

    assert reply_entry["role"] == "assistant" and reply_entry["content"] == "那就好呀"
    assert reply_entry["thought"] == "她其实是在试探我", "独立心想事件未关联到 assistant"

    assert proactive_entry["content"] == "记得吃药哦", "内嵌心想未从正文剥离"
    assert proactive_entry["thought"] == "该提醒她吃药了"
    assert proactive_entry["message_type"] == "text"

    timestamps = [entry["timestamp"] for entry in records]
    assert timestamps == sorted(timestamps), f"应按时间升序返回：{timestamps}"

    contents = " ".join(entry["content"] for entry in records)
    assert "【历史摘要】" not in contents, "摘要条目未被过滤"
    assert "系统事件" not in contents, "非对话 system 事件未被过滤"

    limited = asyncio.run(
        get_conversation_records(conversation_id=CONVERSATION_ID, limit=2)
    )
    assert [entry["content"] for entry in limited] == ["那就好呀", "记得吃药哦"]
    print(f"  [OK] 归一化 3 条对话：心想 {sum('thought' in e for e in records)} 条，limit 生效")


def _check_endpoint(store: ChatHistoryStore) -> None:
    from routers.v1.sessions import get_session_chat_records

    payload = asyncio.run(get_session_chat_records(CONVERSATION_ID, limit=300, before=None))

    assert payload["status"] == "success"
    assert payload["meta"]["count"] == len(payload["data"]) == 3
    assert payload["meta"]["session_id"] == CONVERSATION_ID
    assert payload["data"][1]["thought"] == "她其实是在试探我"
    print("  [OK] 端点形状正确，data/meta 与归一化结果一致")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = ChatHistoryStore(base_dir=Path(tmp))
        refs = _seed(store)
        # get_conversation_records 内部取的是模块级 store 单例，这里换成临时库
        with patch("memory.core.history_ops.get_chat_history_store", lambda: store):
            _check_records(refs)
            _check_endpoint(store)
    print("PASS: 会话真实聊天记录与心想归一化符合预期")


if __name__ == "__main__":
    main()
