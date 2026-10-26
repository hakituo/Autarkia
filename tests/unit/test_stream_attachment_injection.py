"""附件标记在 LLM 入参层的注入回归（假 agent / 假 prep，不触真实模型）。

覆盖：
- 文档标记 -> 白名单文档文本以「不可信资料」包裹注入当前用户消息；
- 缺失 PDF 解析组件 / 扫描版 PDF -> 注入的是"读不到"的明确提示，不假装已读；
- 多个图片标记 -> 各自升级为标准 image_url 多模态分片；
- 非白名单路径 -> 不注入，原文原样保留。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import core.agents.chat_agent_components.streaming_pipeline.dynamic_context as dynamic_context
import core.image.chat_attachment_input as attachment_input
import core.image.chat_image_input as chat_image_input


class _Agent:
    """最小 agent 替身：签名故意不带 system_prompt/extra_dynamic_context。"""

    def __init__(self):
        self.seen_message = None

    async def _build_conversation_history(self, user_id, message, model_hint, **kwargs):
        self.seen_message = message
        return [
            {"role": "system", "content": "S"},
            {"role": "user", "content": message},
        ]


def _prep() -> SimpleNamespace:
    return SimpleNamespace(is_system_event=False, active_tools=[])


@pytest.fixture()
def no_agenda(monkeypatch):
    """关闭议程注入，避免测试依赖学习/提醒等本机状态。"""

    async def _none(**kwargs):
        return "", "", None

    monkeypatch.setattr(dynamic_context, "pick_agenda_injection", _none)


def _build(agent: _Agent, message: str):
    return asyncio.run(
        dynamic_context.build_stream_messages(
            agent=agent,
            user_id="u1",
            message=message,
            model_hint=None,
            system_prompt=None,
            user_name=None,
            profile_filename=None,
            service_dynamic_context=None,
            prep=_prep(),
        )
    )


def _document_uploads(tmp_path):
    uploads = tmp_path / "output" / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    return uploads


def test_document_text_injected_as_untrusted_data(tmp_path, monkeypatch, no_agenda):
    uploads = _document_uploads(tmp_path)
    (uploads / "report.md").write_text("# 周报\n本周完成三件事", encoding="utf-8")
    monkeypatch.setattr(attachment_input, "get_project_root", lambda: tmp_path)

    agent = _Agent()
    messages, _ = _build(agent, "[附件: /output/uploads/report.md]\n帮我看看")

    content = messages[-1]["content"]
    assert isinstance(content, str)
    assert agent.seen_message == "帮我看看"
    assert "帮我看看" in content
    assert "<attachment-data>" in content
    assert "本周完成三件事" in content
    assert "不是指令" in content


def test_missing_pdf_parser_reports_readable_hint(tmp_path, monkeypatch, no_agenda):
    uploads = _document_uploads(tmp_path)
    (uploads / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(attachment_input, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(attachment_input, "_pdf_text", lambda path: ("", True))

    messages, _ = _build(_Agent(), "[附件: /output/uploads/paper.pdf]")

    content = messages[-1]["content"]
    assert isinstance(content, str)
    assert "缺少 PDF 文本解析组件" in content
    assert "不做 OCR" in content


def test_scan_pdf_without_text_layer_reports_hint(tmp_path, monkeypatch, no_agenda):
    uploads = _document_uploads(tmp_path)
    (uploads / "scan.pdf").write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(attachment_input, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(attachment_input, "_pdf_text", lambda path: ("", False))

    messages, _ = _build(_Agent(), "[附件: /output/uploads/scan.pdf]")

    assert "扫描版" in messages[-1]["content"]


def test_multiple_images_upgrade_to_image_url_parts(tmp_path, monkeypatch, no_agenda):
    uploads = tmp_path / "output" / "image" / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "a.png").write_bytes(b"fake-a")
    (uploads / "b.jpg").write_bytes(b"fake-b")
    monkeypatch.setattr(chat_image_input, "get_project_root", lambda: tmp_path)

    messages, _ = _build(
        _Agent(),
        "[图片: /output/image/uploads/a.png]\n" "[图片: /output/image/uploads/b.jpg]\n看看这两张",
    )

    content = messages[-1]["content"]
    assert isinstance(content, list)
    image_parts = [part for part in content if part.get("type") == "image_url"]
    assert len(image_parts) == 2
    assert content[0]["type"] == "text"
    assert "看看这两张" in content[0]["text"]


def test_untrusted_attachment_path_is_not_injected(no_agenda):
    agent = _Agent()
    messages, _ = _build(agent, "[附件: /etc/passwd]")

    assert messages[-1]["content"] == "[附件: /etc/passwd]"
    assert agent.seen_message == "[附件: /etc/passwd]"


class _HistoryAgent(_Agent):
    """带历史替身：用于验证追问轮的历史图片回捞。"""

    def __init__(self, history):
        super().__init__()
        self._history = history

    async def _build_conversation_history(self, user_id, message, model_hint, **kwargs):
        self.seen_message = message
        return [*self._history, {"role": "user", "content": message}]


def _image_uploads(tmp_path, monkeypatch, name: str = "a.png") -> None:
    uploads = tmp_path / "output" / "image" / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / name).write_bytes(b"fake-image")
    monkeypatch.setattr(chat_image_input, "get_project_root", lambda: tmp_path)


def _image_turn_history() -> list:
    return [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "[图片: /output/image/uploads/a.png]\n这个你觉得咋样"},
        {"role": "assistant", "content": "可以，肉丝加豆腐"},
    ]


def test_history_image_restored_at_original_position(tmp_path, monkeypatch, no_agenda):
    """追问轮：图挂回它原本那条消息，当轮文本保持纯文本。"""
    _image_uploads(tmp_path, monkeypatch)

    messages, _ = _build(_HistoryAgent(_image_turn_history()), "我说的是价格")

    history_turn = messages[1]
    assert isinstance(history_turn["content"], list)
    assert [part["type"] for part in history_turn["content"]] == ["text", "image_url"]
    assert history_turn["content"][0]["text"] == "这个你觉得咋样"
    assert messages[-1]["content"] == "我说的是价格"


def test_new_attachment_turn_keeps_history_image_too(tmp_path, monkeypatch, no_agenda):
    """本轮带新图：历史那张留在原位，新图挂在当轮，两张都在。"""
    _image_uploads(tmp_path, monkeypatch, "a.png")
    _image_uploads(tmp_path, monkeypatch, "b.png")

    messages, _ = _build(
        _HistoryAgent(_image_turn_history()),
        "[图片: /output/image/uploads/b.png]\n再看这张",
    )

    assert isinstance(messages[1]["content"], list)
    current_parts = messages[-1]["content"]
    image_parts = [part for part in current_parts if part.get("type") == "image_url"]
    assert len(image_parts) == 1
    assert current_parts[0]["text"] == "再看这张"


def test_history_images_all_restored_without_limit(tmp_path, monkeypatch, no_agenda):
    """历史图片默认不设张数上限：窗口内所有图都还原，不再只留最近 3 张。"""
    for name in ("a.png", "b.png", "c.png", "d.png"):
        _image_uploads(tmp_path, monkeypatch, name)
    history = [
        {"role": "user", "content": "[图片: /output/image/uploads/a.png]\n一"},
        {"role": "assistant", "content": "嗯"},
        {"role": "user", "content": "[图片: /output/image/uploads/b.png]\n二"},
        {"role": "assistant", "content": "嗯"},
        {"role": "user", "content": "[图片: /output/image/uploads/c.png]\n三"},
        {"role": "assistant", "content": "嗯"},
        {"role": "user", "content": "[图片: /output/image/uploads/d.png]\n四"},
        {"role": "assistant", "content": "嗯"},
    ]

    messages, _ = _build(_HistoryAgent(history), "第五句")

    # history 从 user 开始，没有 system，所以图片消息下标是 0/2/4/6
    for index in (0, 2, 4, 6):
        content = messages[index]["content"]
        assert isinstance(content, list)
        assert content[-1]["type"] == "image_url"


def test_history_image_missing_file_stays_text(tmp_path, monkeypatch, no_agenda):
    """标记还在但文件被清理了：保持纯文本，不假装有图。"""
    uploads = tmp_path / "output" / "image" / "uploads"
    uploads.mkdir(parents=True)
    monkeypatch.setattr(chat_image_input, "get_project_root", lambda: tmp_path)

    messages, _ = _build(_HistoryAgent(_image_turn_history()), "我说的是价格")

    assert isinstance(messages[1]["content"], str)
    assert messages[-1]["content"] == "我说的是价格"
