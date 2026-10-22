"""按网址抓取网页正文（fetch_url）的工具包。"""

from .extract import FetchResult, clean_text, extract_text
from .tool import DEFAULT_MAX_CHARS, WebFetchTool

__all__ = [
    "DEFAULT_MAX_CHARS",
    "FetchResult",
    "WebFetchTool",
    "clean_text",
    "extract_text",
]
