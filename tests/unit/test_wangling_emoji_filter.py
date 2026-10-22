import asyncio
import json
import tempfile
from pathlib import Path

from clients.bots.qq.utils import (
    EMOJI_ALLOWLIST_ENABLED,
    _allowed_emoji_cache,
    clean_qq_text,
)
from clients.bots.qq.session.message import SessionMessageHandler
from core.agents.chat_agent_components import history as history_mod
from core.agents.chat_agent_components.history import save_conversation_history
from core.services.chat_history_store import ChatHistoryStore


def test_clean_qq_text_preserves_all_when_allowlist_is_disabled():
    _allowed_emoji_cache.clear()
    _allowed_emoji_cache["test_wangling"] = set()

    result = clean_qq_text("好开心🎉 但是也有点😣", "test_wangling")

    assert EMOJI_ALLOWLIST_ENABLED is False
    assert result == "好开心🎉 但是也有点😣"
    _allowed_emoji_cache.clear()


def test_clean_qq_text_keeps_ellipsis():
    """省略号一律保留：句中、句尾、句首都不删（旧实现会全局删掉）。"""
    _allowed_emoji_cache.clear()
    _allowed_emoji_cache["test_wangling"] = set()

    # 句中
    assert clean_qq_text("嗯…好的", "test_wangling") == "嗯…好的"
    assert clean_qq_text("嗯……好的", "test_wangling") == "嗯……好的"
    # 句尾
    assert clean_qq_text("好开心🎉……", "test_wangling") == "好开心🎉……"
    # 句首（2026-10-17 修：句首省略号曾被整条删掉）
    assert clean_qq_text("……嗯，我知道了", "test_wangling") == "……嗯，我知道了"
    assert clean_qq_text("……", "test_wangling") == "……"

    _allowed_emoji_cache.clear()


def test_clean_qq_text_keeps_ellipsis_when_persona_load_failed():
    """人设加载失败时 emoji 与省略号都保留（清洗不依赖人设）。"""
    _allowed_emoji_cache.clear()

    result = clean_qq_text("嗯…好的……", "missing_persona_for_test")
    assert result == "嗯…好的……"


def test_clean_qq_text_removes_period_before_emoji():
    _allowed_emoji_cache.clear()
    _allowed_emoji_cache["test_ling_b"] = {"🖤"}

    assert clean_qq_text("知道了。🖤", "test_ling_b") == "知道了🖤"
    assert clean_qq_text("知道了. 🖤", "test_ling_b") == "知道了 🖤"
    assert clean_qq_text("知道了。再说", "test_ling_b") == "知道了。再说"
    assert clean_qq_text("知道了。🎉", "test_ling_b") == "知道了🎉"

    _allowed_emoji_cache.clear()


def test_clean_qq_text_keeps_text_when_persona_load_failed():
    _allowed_emoji_cache.clear()

    result = clean_qq_text("好开心🎉", "missing_persona_for_test")

    assert result == "好开心🎉"


def test_save_conversation_history_preserves_emoji_and_normalizes_period():
    class DummyMemoryManager:
        def __init__(self):
            self.calls = []

        def add_memory(self, **kwargs):
            self.calls.append(kwargs)
            return f"mid-{len(self.calls)}"

        def _schedule_save(self):
            return None

    class DummyAgent:
        def __init__(self):
            self.mm = DummyMemoryManager()
            self.llm_module = None

        def _get_memory_manager(self, user_id):
            return self.mm

        def _is_study_mode(self, message, model_hint=None):
            return False

    async def _run():
        _allowed_emoji_cache.clear()
        _allowed_emoji_cache["test_wangling"] = set()

        tmpdir = tempfile.mkdtemp(prefix="wangling-emoji-history-")
        history_mod.get_chat_history_store = lambda: ChatHistoryStore(Path(tmpdir))

        agent = DummyAgent()
        await save_conversation_history(
            agent=agent,
            user_id="debug_user",
            user_msg="测试",
            assistant_msg="好开心。🎉",
            message_id="msg-1",
            profile_filename="test_wangling",
        )

        assert agent.mm.calls[1]["content"] == "好开心🎉"
        stored_file = next(Path(tmpdir).rglob("*.jsonl"))
        stored_text = stored_file.read_text(encoding="utf-8")
        assert "好开心。🎉" not in stored_text
        assert "好开心🎉" in stored_text
        _allowed_emoji_cache.clear()

    asyncio.run(_run())


def test_clean_qq_text_default_still_flattens_blank_lines():
    """默认口径（QQ 发送路径）不变：空行仍压成单空格。

    发送路径本来就会按行把回复切成多条消息，不需要空行结构；只有历史落库要保留。
    """
    _allowed_emoji_cache.clear()
    _allowed_emoji_cache["test_wangling"] = set()

    assert clean_qq_text("第一句\n\n第二句", "test_wangling") == "第一句 第二句"

    _allowed_emoji_cache.clear()


def test_clean_qq_text_preserve_paragraphs_keeps_blank_lines():
    """历史落库口径：保留空行结构，模型才能看到自己回复的分行。"""
    _allowed_emoji_cache.clear()
    _allowed_emoji_cache["test_wangling"] = set()

    assert (
        clean_qq_text("第一句\n\n第二句\n\n第三句", "test_wangling", preserve_paragraphs=True)
        == "第一句\n\n第二句\n\n第三句"
    )
    # 行内多余空白与 3 个以上连续换行仍要归一
    assert (
        clean_qq_text("第一句  第二句\n\n\n\n第三句", "test_wangling", preserve_paragraphs=True)
        == "第一句 第二句\n\n第三句"
    )
    # 只含空白的"空行"要归一成真正的空行
    assert (
        clean_qq_text("第一句\n   \n第二句", "test_wangling", preserve_paragraphs=True)
        == "第一句\n\n第二句"
    )

    _allowed_emoji_cache.clear()


def test_save_conversation_history_preserves_blank_lines():
    """落库路径必须保留空行：模型回看历史时靠它看到自己的分句结构。

    压平会让模型只能看到一整行空格分隔的文本，反过来强化"用空格分句"的写法，
    而那正是客户端断句被切碎的上游诱因。
    """

    class DummyMemoryManager:
        def __init__(self):
            self.calls = []

        def add_memory(self, **kwargs):
            self.calls.append(kwargs)
            return f"mid-{len(self.calls)}"

        def _schedule_save(self):
            return None

    class DummyAgent:
        def __init__(self):
            self.mm = DummyMemoryManager()
            self.llm_module = None

        def _get_memory_manager(self, user_id):
            return self.mm

        def _is_study_mode(self, message, model_hint=None):
            return False

    async def _run():
        _allowed_emoji_cache.clear()
        _allowed_emoji_cache["test_wangling"] = set()

        tmpdir = tempfile.mkdtemp(prefix="wangling-paragraph-history-")
        history_mod.get_chat_history_store = lambda: ChatHistoryStore(Path(tmpdir))

        await save_conversation_history(
            agent=DummyAgent(),
            user_id="debug_user",
            user_msg="测试",
            assistant_msg="第一句\n\n第二句",
            message_id="msg-paragraph-1",
            profile_filename="test_wangling",
        )

        files = [
            path
            for path in Path(tmpdir).rglob("*.jsonl")
            if "chat_reply" in path.read_text(encoding="utf-8")
        ]
        assert files, "没有写出含 chat_reply 的历史文件"
        records = [
            json.loads(line)
            for path in files
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assistant = next(r for r in records if r.get("event_type") == "chat_reply")
        assert assistant["content"] == "第一句\n\n第二句"

        _allowed_emoji_cache.clear()

    asyncio.run(_run())


def test_qq_outbound_applies_emoji_filter_before_send():
    class DummyConfig:
        auto_tts_for_voice_input = False

    class DummyAdapter:
        config_handler = None
        _session_prefs = {}
        reply_voice_only = False

        def __init__(self):
            self.sent = []

        async def send_to_napcat(self, session_id, content):
            self.sent.append((session_id, content))

    class DummySession:
        session_id = "private_123456789"
        _cfg = DummyConfig()
        is_voice_input = False

        def __init__(self):
            self.adapter = DummyAdapter()

        @staticmethod
        def _get_current_profile_filename():
            return "test_ling_b"

    async def _run():
        _allowed_emoji_cache.clear()
        _allowed_emoji_cache["test_ling_b"] = set()
        session = DummySession()
        handler = SessionMessageHandler(session)

        await handler.send_response("知道了。🎉", allow_session_tts=False)

        assert session.adapter.sent == [("private_123456789", "知道了🎉")]
        _allowed_emoji_cache.clear()

    asyncio.run(_run())
