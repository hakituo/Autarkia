"""文本归一化与配对辅助；规则与 Android ``TextSegmenter.clean`` 对齐。

手机侧的正文被清过句末标点，服务端还保留原始标点，所以配对前统一：
去 NFKC、去方括号标记（表情包 / 时间戳 / 媒体路径）、去标点与空白。
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_PUNCTUATION = frozenset(
    '''!"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~，。！？、；：“”‘’（）【】《》…—·～　'''
)
_MEDIA = re.compile(
    r"^\s*\[(?:图片|照片|视频|语音|文件|附件|IMG|BM|VOICE|FILE)"
    r"(?:[:：][^\]]*)?\]\s*",
    re.IGNORECASE,
)
_BRACKET = re.compile(r"\[[^\]]{0,40}\]")
_WRAPPER = "【用户最新消息】"


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).lower()
    value = _MEDIA.sub("", value)
    value = _BRACKET.sub("", value)
    return "".join(
        char for char in value if char not in _PUNCTUATION and not char.isspace()
    )


def has_media_prefix(text: str) -> bool:
    return bool(_MEDIA.match(str(text or "")))


def strip_media_prefix(text: str) -> str:
    return _MEDIA.sub("", str(text or ""), count=1).strip()


def latest_wrapper_message(text: str) -> str:
    raw = str(text or "")
    if _WRAPPER not in raw:
        return ""
    return raw.rsplit(_WRAPPER, 1)[-1].strip()


def quick_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right, autojunk=False).quick_ratio()


def similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


__all__ = [
    "has_media_prefix",
    "latest_wrapper_message",
    "normalize_text",
    "quick_similarity",
    "similarity",
    "strip_media_prefix",
]
