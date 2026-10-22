"""HTML → 纯文本提取（fetch_url 专用，标准库实现，不引额外依赖）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import List, Tuple

_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe", "canvas"}
_BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "main", "aside", "nav",
    "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "br", "hr", "pre", "blockquote",
    "table", "ul", "ol", "dl", "dt", "dd", "figure", "figcaption", "form", "title",
}


@dataclass(frozen=True)
class FetchResult:
    title: str
    text: str
    final_url: str
    content_type: str


class _TextExtractor(HTMLParser):
    """把 HTML 压成纯文本，剔除脚本、样式和无语义标签。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._title_parts: List[str] = []
        self._chunks: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "title":
            self._in_title = False
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
            return
        self._chunks.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self._title_parts).split())

    @property
    def raw_text(self) -> str:
        return "".join(self._chunks)


def clean_text(raw: str) -> str:
    """压缩空白与空行，丢掉纯符号行，并合并「短前缀 + 完整行」这类重复。"""
    lines: List[str] = []
    for line in raw.replace("\r", "\n").split("\n"):
        cleaned = re.sub(r"[ \t\u00a0]+", " ", line).strip()
        if not cleaned:
            continue
        if not re.search(r"[0-9A-Za-z\u4e00-\u9fff]", cleaned):
            continue
        # 页面常把同一个指标拆成「31」+「个子服务」两段（sr-only 标签），保留长的那行。
        if lines and (lines[-1].endswith(cleaned) or cleaned.endswith(lines[-1])):
            if len(cleaned) > len(lines[-1]):
                lines[-1] = cleaned
            continue
        lines.append(cleaned)
    return "\n".join(lines)


def extract_text(html: str) -> Tuple[str, str]:
    """返回 (标题, 正文)；半截 HTML 也尽量给出能读的内容。"""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - 解析失败不应让抓取整体失败
        pass
    return parser.title, clean_text(parser.raw_text)
