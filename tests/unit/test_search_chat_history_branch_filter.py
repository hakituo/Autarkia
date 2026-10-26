"""search_chat_history 的分支过滤接线测试。

回滚 + 重新生成后，被回滚掉的分支内容不该再被搜回来——过滤发生在工具
合并候选后、截断前，只有带 history_override 的请求（ContextVar 里有边界）
才生效。
"""

from core.agents.chat_agent_components.message_branch import (
    reset_chat_history_branch_scope,
    set_chat_history_branch_scope,
)
from core.tools.search_chat_history_tool import SearchChatHistoryTool


def _event(**overrides):
    payload = {
        "conversation_id": "web_role_aveline",
        "message_id": "node",
        "timestamp": 100.0,
        "role": "user",
        "content": "AvelineNTR呢",
    }
    payload.update(overrides)
    return payload


def test_filter_hides_abandoned_branch_events():
    token = set_chat_history_branch_scope({"node-a"}, 100.0)
    try:
        events = [
            _event(message_id="node-a", timestamp=100.0),  # 路径上
            _event(message_id="node-old", timestamp=50.0),  # 分支点前的旧历史
            _event(message_id="node-b", timestamp=120.0),  # 被回滚掉的分支
            _event(
                conversation_id="private_123456789",
                message_id="qq",
                timestamp=999.0,
            ),  # 其它会话
        ]
        kept = SearchChatHistoryTool._filter_branch_visible(events, "web_role_aveline")
        assert [e["message_id"] for e in kept] == ["node-a", "node-old", "qq"]
    finally:
        reset_chat_history_branch_scope(token)


def test_filter_is_noop_without_branch_scope():
    events = [_event(message_id="node-b", timestamp=120.0)]
    assert SearchChatHistoryTool._filter_branch_visible(events, "web_role_aveline") == events


def test_filter_keeps_everything_for_empty_event_list():
    token = set_chat_history_branch_scope(set(), 0.0)
    try:
        assert SearchChatHistoryTool._filter_branch_visible([], "web_role_aveline") == []
    finally:
        reset_chat_history_branch_scope(token)
