"""聊天图片输入辅助。

Android 图片消息使用 ``[图片: /output/image/uploads/xxx]`` 作为轻量附件标记。
本模块负责：
1. 从用户消息中拆出附件路径与真实 caption；
2. 只允许读取后端上传目录内的图片；
3. 把图片编码成 OpenAI 兼容的 data URI，交给统一视觉路由。

这里不判断模型是否支持视觉。模型能力判断统一由
``core.llm.model_capabilities`` / ``vision_router`` 负责，避免两套名单漂移。
"""

from __future__ import annotations

import asyncio
import base64
import re
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple
from urllib.parse import urlparse

from core.utils.common import get_project_root
from core.utils.logger import get_logger

logger = get_logger("ChatImageInput")

_IMAGE_MESSAGE_RE = re.compile(
    r"^\[图片:\s*(?P<path>[^\]\r\n]+)\]\s*(?P<caption>.*)$",
    re.DOTALL,
)
_DEFAULT_IMAGE_TEXT = "（用户发送了一张图片）"
_MAX_IMAGE_BYTES = 16 * 1024 * 1024
_MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}

# 历史消息里的图片按**原位置**还原成 image_url（主流产品都是「图一直在上下文里」）。
# 张数与字节数封顶，避免一次带太多图把请求体撑大。
HISTORY_IMAGE_MAX_COUNT = 3
HISTORY_IMAGE_MAX_BYTES = 24 * 1024 * 1024

# 历史消息里的标记不一定在行首（可能被 caption 或其他标记包着），
# 所以这里用 search 版正则，不复用只做整条消息匹配的 _IMAGE_MESSAGE_RE。
_IMAGE_MARKER_SEARCH_RE = re.compile(r"\[图片:\s*(?P<path>[^\]\r\n]+)\]")


def _normalize_uploaded_image_ref(image_ref: str) -> Optional[str]:
    """把相对地址/完整后端 URL 归一化成上传目录路径。"""
    token = str(image_ref or "").strip().strip('"').strip("'")
    if not token:
        return None

    parsed = urlparse(token)
    if parsed.scheme in {"http", "https"}:
        token = parsed.path
    elif parsed.scheme:
        return None

    normalized = "/" + token.lstrip("/")
    if not normalized.startswith("/output/image/uploads/"):
        return None
    return normalized


def split_chat_image_message(message: Any) -> Tuple[Any, Optional[str]]:
    """拆出 Android 图片附件标记，返回（真实用户文本，图片路径）。"""
    if not isinstance(message, str):
        return message, None

    match = _IMAGE_MESSAGE_RE.match(message.strip())
    if not match:
        return message, None

    image_ref = _normalize_uploaded_image_ref(match.group("path"))
    if image_ref is None:
        return message, None

    caption = str(match.group("caption") or "").strip()
    return caption or _DEFAULT_IMAGE_TEXT, image_ref


def _resolve_uploaded_image_path(image_ref: str) -> Optional[Path]:
    """只解析 ``output/image/uploads`` 目录内的文件，阻止路径穿越。"""
    normalized = _normalize_uploaded_image_ref(image_ref)
    if normalized is None:
        return None

    project_root = Path(get_project_root()).resolve()
    uploads_root = (project_root / "output" / "image" / "uploads").resolve()
    candidate = (project_root / normalized.lstrip("/")).resolve()

    try:
        candidate.relative_to(uploads_root)
    except ValueError:
        return None

    if not candidate.is_file():
        return None
    if candidate.suffix.lower() not in _MIME_BY_SUFFIX:
        return None
    return candidate


async def load_uploaded_image_data_url(image_ref: str) -> Optional[str]:
    """读取已上传图片并编码为标准 ``data:image/...;base64`` URL。"""
    image_path = _resolve_uploaded_image_path(image_ref)
    if image_path is None:
        logger.warning("聊天图片附件路径无效或文件不存在: %s", image_ref)
        return None

    try:
        file_size = image_path.stat().st_size
    except OSError as exc:
        logger.warning("读取聊天图片附件大小失败: %s", exc)
        return None

    if file_size <= 0 or file_size > _MAX_IMAGE_BYTES:
        logger.warning("聊天图片附件大小异常: path=%s size=%d", image_path, file_size)
        return None

    try:
        image_bytes = await asyncio.to_thread(image_path.read_bytes)
    except OSError as exc:
        logger.warning("读取聊天图片附件失败: %s", exc)
        return None

    mime = _MIME_BY_SUFFIX.get(image_path.suffix.lower())
    if not mime:
        return None
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _iter_text_chunks(content: Any) -> Iterator[str]:
    """把消息 content 归一化成若干段文本（兼容纯文本与多模态分片）。"""
    if isinstance(content, str):
        yield content
        return
    if not isinstance(content, list):
        return
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if text:
                yield str(text)


def find_image_refs_in_message(content: Any) -> List[str]:
    """抽出一条消息里的所有图片引用（白名单内、去重、按出现顺序）。"""
    refs: List[str] = []
    seen: set[str] = set()
    for chunk in _iter_text_chunks(content):
        for match in _IMAGE_MARKER_SEARCH_RE.finditer(chunk):
            ref = _normalize_uploaded_image_ref(match.group("path"))
            if ref and ref not in seen:
                seen.add(ref)
                refs.append(ref)
    return refs


def _strip_image_markers(text: str) -> str:
    return _IMAGE_MARKER_SEARCH_RE.sub("", text).strip()


async def restore_history_images(
    messages: Any,
    max_images: int = HISTORY_IMAGE_MAX_COUNT,
    max_bytes: int = HISTORY_IMAGE_MAX_BYTES,
) -> int:
    """把历史消息里的 ``[图片: path]`` 标记还原成 image_url 附件（**原位置**）。

    主流聊天产品都是这么做的：图留在它被发送的那条消息里，后续每一轮都能看到。
    历史落库只存文本标记，所以每轮重建 prompt 时按标记把图读回来即可，
    不需要摘要，也不需要判断「这轮是不是在追问」。

    预算从新到旧分配：先保证最近的图；超出张数/字节上限的旧图保持纯文本。
    返回实际还原的张数。
    """
    if max_images <= 0 or max_bytes <= 0 or not isinstance(messages, list):
        return 0

    remaining_count = max_images
    remaining_bytes = max_bytes
    restored = 0

    for msg in reversed(messages):
        if remaining_count <= 0 or remaining_bytes <= 0:
            break
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        refs = find_image_refs_in_message(msg.get("content"))
        if not refs:
            continue

        image_parts: List[dict] = []
        for ref in refs:
            if remaining_count <= 0:
                break
            data_url = await load_uploaded_image_data_url(ref)
            if not data_url:
                continue
            estimated_bytes = len(data_url) * 3 // 4
            if estimated_bytes > remaining_bytes:
                continue
            remaining_bytes -= estimated_bytes
            remaining_count -= 1
            image_parts.append(
                {"type": "image_url", "image_url": {"url": data_url}}
            )

        if not image_parts:
            continue

        text = "\n".join(
            _strip_image_markers(chunk)
            for chunk in _iter_text_chunks(msg.get("content"))
        ).strip()
        msg["content"] = [
            {"type": "text", "text": text or _DEFAULT_IMAGE_TEXT},
            *image_parts,
        ]
        restored += len(image_parts)

    return restored
