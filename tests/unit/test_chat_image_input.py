from __future__ import annotations

import asyncio
import base64

import core.image.chat_image_input as chat_image_input


def test_split_chat_image_message_extracts_caption_and_path():
    text, image_ref = chat_image_input.split_chat_image_message(
        "[图片: /output/image/uploads/a.jpg]\n帮我看看这张图"
    )

    assert text == "帮我看看这张图"
    assert image_ref == "/output/image/uploads/a.jpg"


def test_split_chat_image_message_uses_placeholder_for_image_only():
    text, image_ref = chat_image_input.split_chat_image_message(
        "[图片: /output/image/uploads/a.png]"
    )

    assert text == "（用户发送了一张图片）"
    assert image_ref == "/output/image/uploads/a.png"


def test_split_chat_image_message_rejects_non_upload_path():
    original = "[图片: /etc/passwd]"
    text, image_ref = chat_image_input.split_chat_image_message(original)

    assert text == original
    assert image_ref is None


def test_load_uploaded_image_data_url_reads_only_upload_directory(tmp_path, monkeypatch):
    raw = b"fake-png-bytes"
    uploads = tmp_path / "output" / "image" / "uploads"
    uploads.mkdir(parents=True)
    image_path = uploads / "sample.png"
    image_path.write_bytes(raw)

    monkeypatch.setattr(chat_image_input, "get_project_root", lambda: tmp_path)

    data_url = asyncio.run(
        chat_image_input.load_uploaded_image_data_url("/output/image/uploads/sample.png")
    )

    assert data_url is not None
    prefix, encoded = data_url.split(",", 1)
    assert prefix == "data:image/png;base64"
    assert base64.b64decode(encoded) == raw

    outside = tmp_path / "output" / "image" / "secret.png"
    outside.write_bytes(raw)
    rejected = asyncio.run(
        chat_image_input.load_uploaded_image_data_url("/output/image/uploads/../secret.png")
    )
    assert rejected is None


def test_find_image_refs_in_message_extracts_all_and_dedupes():
    content = (
        "[图片: /output/image/uploads/a.png]\n"
        "[图片: /output/image/uploads/a.png]\n"
        "[图片: /etc/passwd]\n看看"
    )

    assert chat_image_input.find_image_refs_in_message(content) == ["/output/image/uploads/a.png"]


def test_find_image_refs_in_message_reads_multimodal_text_parts():
    content = [
        {"type": "text", "text": "[图片: /output/image/uploads/b.jpg]\n看看"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,xx"}},
    ]

    assert chat_image_input.find_image_refs_in_message(content) == ["/output/image/uploads/b.jpg"]


def test_find_image_refs_in_message_tolerates_bad_input():
    assert chat_image_input.find_image_refs_in_message(None) == []
    assert chat_image_input.find_image_refs_in_message({"a": 1}) == []


def _write_upload(tmp_path, name: str) -> None:
    uploads = tmp_path / "output" / "image" / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / name).write_bytes(b"fake-" + name.encode())


def test_restore_history_images_rewrites_message_in_place(tmp_path, monkeypatch):
    _write_upload(tmp_path, "a.png")
    monkeypatch.setattr(chat_image_input, "get_project_root", lambda: tmp_path)
    messages = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "[图片: /output/image/uploads/a.png]\n这个你觉得咋样"},
        {"role": "assistant", "content": "可以，肉丝加豆腐"},
    ]

    restored = asyncio.run(chat_image_input.restore_history_images(messages))

    assert restored == 1
    content = messages[1]["content"]
    assert [part["type"] for part in content] == ["text", "image_url"]
    assert content[0]["text"] == "这个你觉得咋样"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert isinstance(messages[2]["content"], str)


def test_restore_history_images_prefers_newest_and_respects_limit(tmp_path, monkeypatch):
    for name in ("a.png", "b.png", "c.png"):
        _write_upload(tmp_path, name)
    monkeypatch.setattr(chat_image_input, "get_project_root", lambda: tmp_path)
    messages = [
        {"role": "user", "content": "[图片: /output/image/uploads/a.png]\n一"},
        {"role": "user", "content": "[图片: /output/image/uploads/b.png]\n二"},
        {"role": "user", "content": "[图片: /output/image/uploads/c.png]\n三"},
    ]

    restored = asyncio.run(chat_image_input.restore_history_images(messages, max_images=2))

    assert restored == 2
    assert isinstance(messages[0]["content"], str)
    assert isinstance(messages[1]["content"], list)
    assert isinstance(messages[2]["content"], list)


def test_restore_history_images_default_has_no_count_limit(tmp_path, monkeypatch):
    """默认不设张数上限：历史窗口内的图全部还原。"""
    names = ("a.png", "b.png", "c.png", "d.png", "e.png")
    for name in names:
        _write_upload(tmp_path, name)
    monkeypatch.setattr(chat_image_input, "get_project_root", lambda: tmp_path)
    messages = [
        {"role": "user", "content": f"[图片: /output/image/uploads/{name}]\n{name}"}
        for name in names
    ]

    restored = asyncio.run(chat_image_input.restore_history_images(messages))

    assert restored == len(names)
    assert all(isinstance(msg["content"], list) for msg in messages)


def test_restore_history_images_keeps_text_when_file_missing(tmp_path, monkeypatch):
    uploads = tmp_path / "output" / "image" / "uploads"
    uploads.mkdir(parents=True)
    monkeypatch.setattr(chat_image_input, "get_project_root", lambda: tmp_path)
    messages = [
        {"role": "user", "content": "[图片: /output/image/uploads/gone.png]\n看图"},
    ]

    restored = asyncio.run(chat_image_input.restore_history_images(messages))

    assert restored == 0
    assert messages[0]["content"] == "[图片: /output/image/uploads/gone.png]\n看图"


def test_restore_history_images_tolerates_bad_input():
    assert asyncio.run(chat_image_input.restore_history_images(None)) == 0
    assert asyncio.run(chat_image_input.restore_history_images([], max_images=0)) == 0
