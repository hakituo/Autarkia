"""
测试分级模式判定

判定口径收敛后有两个真源层级：
1. ``sensitive_prefix.is_sensitive_persona``：这个人设是否属于分级人设
   （路径含 sensitive 段，或权威画像 ``sensitive=True``）；
2. ``mode_control.check_sensitive_mode``：这一轮是否进入分级模式
   （显式指令 > 人设 > 记忆开关）。

本文件同时守两条：人设路径与人设画像都要能触发分级模式，且显式关闭指令必须
压过前两者——否则用户写过一次开启之后永远退不出去。
"""

from core.agents.chat_agent_components.persona_system.prompt.mode_control import (
    check_sensitive_mode,
    is_mode_off_content,
    is_mode_on_content,
    mode_toggle_from_message,
    resolve_memory_mode_toggle,
)


class _MemoryManager:
    def __init__(self, memories):
        self._memories = memories

    def get_memories_by_topic(self, topic, limit=1):
        return self._memories[:limit]


class _Agent:
    def __init__(self, memories=None):
        self._memories = memories if memories is not None else []

    def _get_memory_manager(self, cid):
        return _MemoryManager(self._memories)


def _check(profile_filename="core_aveline.json", message="你好", memories=None):
    return check_sensitive_mode(
        _Agent(memories), "user_1", message, profile_filename
    )


def test_sensitive_persona_path():
    """人设文件位于 sensitive 目录下即为分级模式"""
    assert _check("variants/ling_b.json")
    assert _check("/abs/path/variants/test.json")
    assert _check("D:\\personas\\sensitive\\test.json")


def test_sensitive_persona_profile():
    """画像标了 sensitive 的角色即使不在 sensitive 目录也算分级人设"""
    assert _check("core_ye.json")
    assert _check("ye/core_ye.json")


def test_archived_persona_is_not_sensitive():
    """归档到 legacy/ 的人设不再触发分级模式"""
    assert not _check("legacy/Frost/Frost.json")
    assert not _check("legacy/variants/old.json")


def test_normal_persona_path_is_not_sensitive():
    assert not _check("core_aveline.json")
    assert not _check("study/Aveline_Study.json")
    assert not _check("core_ling.json")


def test_sensitive_mode_switch_in_memory():
    """记忆里的分级模式开关优先于默认人设"""
    memories = [{"content": "SENSITIVE_MODE_ON"}]
    assert _check(memories=memories)

    assert not _check(memories=[{"content": "随便一条记忆"}])


def test_latest_memory_wins_over_stale_on():
    """ON 之后写过 OFF，必须按最新一条判定（关闭要能真正生效）"""
    memories = [
        {"content": "SYSTEM_COMMAND: SENSITIVE_MODE_ON", "metadata": {"timestamp": 100.0}},
        {"content": "SYSTEM_COMMAND: SENSITIVE_MODE_OFF", "metadata": {"timestamp": 200.0}},
    ]
    assert resolve_memory_mode_toggle(memories) is False
    assert not _check(memories=memories)

    # 列表顺序反过来也应得到同一结论（按 timestamp 排序，不靠位置）
    reversed_memories = list(reversed(memories))
    assert resolve_memory_mode_toggle(reversed_memories) is False
    assert not _check(memories=reversed_memories)


def test_off_marker_is_not_read_as_on():
    """OFF 记录不能被子串包含误判成 ON"""
    assert is_mode_off_content("SYSTEM_COMMAND: SENSITIVE_MODE_OFF")
    assert not is_mode_on_content("SYSTEM_COMMAND: SENSITIVE_MODE_OFF")
    assert is_mode_on_content("SYSTEM_COMMAND: SENSITIVE_MODE_ON")


def test_sensitive_command_in_message():
    """消息里的分级模式指令同样生效"""
    for message in ("/sensitive", "[sensitive]", "开启sensitive", "/private", "[private]"):
        assert _check(message=message), f"{message} 应触发分级模式"

    assert not _check(message="今天天气不错")


def test_explicit_off_command_wins():
    """显式关闭指令压过人设与记忆开关"""
    for message in ("/sensitive off", "关闭分级模式", "关闭sensitive", "/private off", "退出私密模式"):
        assert mode_toggle_from_message(message) is False
        # 分级人设 + 记忆开着，也要被当前这句关掉
        assert not _check(
            profile_filename="variants/ling_b.json",
            message=message,
            memories=[{"content": "SYSTEM_COMMAND: SENSITIVE_MODE_ON"}],
        ), f"{message} 应关闭分级模式"


def test_sensitive_mode_when_memory_manager_unavailable():
    """记忆管理器不可用时不阻断判定"""
    class _BrokenAgent:
        def _get_memory_manager(self, cid):
            raise RuntimeError("memory unavailable")

    assert check_sensitive_mode(_BrokenAgent(), "user_1", "你好", "core_aveline.json") is False
