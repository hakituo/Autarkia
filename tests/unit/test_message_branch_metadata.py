from types import SimpleNamespace

from core.agents.chat_agent_components.message_branch import (
    branch_metadata_for_role,
    get_chat_history_branch_scope,
    get_request_branch_metadata,
    is_event_visible_in_branch,
    normalize_branch_metadata,
    reset_chat_history_branch_scope,
    reset_request_branch_metadata,
    set_chat_history_branch_scope,
    set_request_branch_metadata,
)
from memory.core.storage import _check_duplicate, _is_low_value_for_weighted


def _branch_payload(**overrides):
    payload = {
        "user_message_id": "android-user",
        "user_parent_id": "android-parent",
        "user_variant_index": 1,
        "user_variant_count": 2,
        "user_variant_of": "android-user-old",
        "assistant_message_id": "android-ai",
        "assistant_parent_id": "android-user",
        "assistant_variant_index": 2,
        "assistant_variant_count": 3,
        "assistant_variant_of": "android-ai-old",
    }
    payload.update(overrides)
    return payload


def test_branch_metadata_normalizes_and_projects_per_role():
    normalized = normalize_branch_metadata(_branch_payload())
    assert normalized is not None

    user = branch_metadata_for_role(normalized, "user")
    assistant = branch_metadata_for_role(normalized, "assistant")

    assert user == {
        "client_message_id": "android-user",
        "parent_id": "android-parent",
        "variant_index": 1,
        "variant_count": 2,
        "variant_of": "android-user-old",
    }
    assert assistant == {
        "client_message_id": "android-ai",
        "parent_id": "android-user",
        "variant_index": 2,
        "variant_count": 3,
        "variant_of": "android-ai-old",
    }


def test_branch_metadata_contextvar_restores_previous_request():
    outer = set_request_branch_metadata(_branch_payload(user_message_id="outer-user"))
    try:
        assert get_request_branch_metadata()["user_message_id"] == "outer-user"
        inner = set_request_branch_metadata(_branch_payload(user_message_id="inner-user"))
        try:
            assert get_request_branch_metadata()["user_message_id"] == "inner-user"
        finally:
            reset_request_branch_metadata(inner)
        assert get_request_branch_metadata()["user_message_id"] == "outer-user"
    finally:
        reset_request_branch_metadata(outer)
    assert get_request_branch_metadata() is None


def test_invalid_branch_metadata_is_rejected():
    assert normalize_branch_metadata({"user_message_id": "only-user"}) is None
    assert normalize_branch_metadata("bad") is None


# ---------------------------------------------------------------------------
# 聊天记录检索的分支边界（回滚 + 重新生成后不搜回被丢弃的分支）
# ---------------------------------------------------------------------------


def _event(**overrides):
    payload = {
        "conversation_id": "web_role_aveline",
        "message_id": "ai-node",
        "timestamp": 100.0,
        "role": "user",
        "content": "AvelineNTR呢",
    }
    payload.update(overrides)
    return payload


def _scope(**overrides):
    payload = {
        "allowed_message_ids": {"ai-node", "user-node"},
        "not_after_ts": 100.0,
    }
    payload.update(overrides)
    return payload


def test_chat_history_branch_scope_contextvar_restores_previous_request():
    outer = set_chat_history_branch_scope({"a"}, 100.0)
    try:
        assert get_chat_history_branch_scope()["not_after_ts"] == 100.0
        inner = set_chat_history_branch_scope({"b"}, None)
        try:
            scope = get_chat_history_branch_scope()
            assert scope["allowed_message_ids"] == {"b"}
            assert scope["not_after_ts"] is None
        finally:
            reset_chat_history_branch_scope(inner)
        assert get_chat_history_branch_scope()["allowed_message_ids"] == {"a"}
    finally:
        reset_chat_history_branch_scope(outer)
    assert get_chat_history_branch_scope() is None


def test_event_on_active_path_is_visible():
    assert is_event_visible_in_branch(
        _event(message_id="ai-node", timestamp=50.0),
        conversation_id="web_role_aveline",
        scope=_scope(),
    )


def test_event_older_than_branch_point_is_visible():
    # 分支点之前的旧历史必须照常可搜，否则长会话下旧往事全丢。
    assert is_event_visible_in_branch(
        _event(message_id="ancient-node", timestamp=99.0),
        conversation_id="web_role_aveline",
        scope=_scope(),
    )


def test_event_after_branch_point_off_path_is_hidden():
    # 晚于分支点、又不在活跃路径上 = 被回滚掉的分支。
    assert not is_event_visible_in_branch(
        _event(message_id="abandoned-node", timestamp=120.0),
        conversation_id="web_role_aveline",
        scope=_scope(),
    )


def test_other_conversation_events_are_untouched():
    # QQ / 旧会话 / 归档不属于当前分支，不能误伤。
    assert is_event_visible_in_branch(
        _event(conversation_id="private_123456789", message_id="qq", timestamp=999.0),
        conversation_id="web_role_aveline",
        scope=_scope(),
    )


def test_proactive_messages_are_untouched():
    event = _event(
        message_id="proactive",
        timestamp=999.0,
        metadata={"is_proactive": True},
    )
    assert is_event_visible_in_branch(event, conversation_id="web_role_aveline", scope=_scope())


def test_missing_timestamp_only_applies_id_rule():
    # 老版本客户端不带时间戳：只按 ID 过滤，不搞时间兜底。
    scope = _scope(not_after_ts=None)
    # 不在路径上、又没有时间边界 → 放行（旧历史不会被误伤）。
    assert is_event_visible_in_branch(
        _event(message_id="abandoned-node", timestamp=999.0),
        conversation_id="web_role_aveline",
        scope=scope,
    )
    # 命中路径 ID → 可见。
    assert is_event_visible_in_branch(
        _event(message_id="ai-node", timestamp=999.0),
        conversation_id="web_role_aveline",
        scope=scope,
    )


def test_empty_override_hides_everything_in_conversation():
    # 显式空路径 = 从零重生成第一轮回复：本会话此前的记录全部不可见。
    scope = _scope(allowed_message_ids=set(), not_after_ts=0.0)
    assert not is_event_visible_in_branch(
        _event(message_id="ancient-node", timestamp=1.0),
        conversation_id="web_role_aveline",
        scope=scope,
    )
    # 但其它会话与主动消息仍不受影响。
    assert is_event_visible_in_branch(
        _event(conversation_id="private_123456789", timestamp=1.0),
        conversation_id="web_role_aveline",
        scope=scope,
    )


def test_no_scope_keeps_everything():
    assert is_event_visible_in_branch(
        _event(message_id="abandoned-node", timestamp=999.0),
        conversation_id="web_role_aveline",
        scope=None,
    )


def test_client_tree_node_is_not_dropped_as_low_value_memory():
    assert not _is_low_value_for_weighted(
        content="嗯",
        source="user",
        category="event",
        is_important=False,
        metadata={"client_message_id": "android-short-node"},
    )
    assert _is_low_value_for_weighted(
        content="嗯",
        source="user",
        category="event",
        is_important=False,
        metadata={},
    )


def test_client_message_id_dedupe_does_not_merge_parallel_same_text():
    memory = {
        "id": "wm-old",
        "content": "完全一样的回复",
        "source": "assistant",
        "category": "event",
        "metadata": {"client_message_id": "android-v2"},
    }
    ctx = SimpleNamespace(
        weighted_memories={"wm-old": memory},
        # 模拟旧版启动重建留下的正文 dedupe key。
        content_dedupe_index={"完全一样的回复\x00assistant\x00event": "wm-old"},
    )

    assert (
        _check_duplicate(
            ctx,
            "完全一样的回复",
            "assistant",
            "event",
            metadata={"client_message_id": "android-v2"},
        )
        == "wm-old"
    )
    assert (
        _check_duplicate(
            ctx,
            "完全一样的回复",
            "assistant",
            "event",
            metadata={"client_message_id": "android-v3"},
        )
        == ""
    )
    # 普通非树记忆也不能误合并到某个 Android 分支节点。
    assert _check_duplicate(ctx, "完全一样的回复", "assistant", "event") == ""
