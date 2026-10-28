"""按请求控制思考模式（thinking）的开关。

部分云模型（DeepSeek / MiniMax / 智谱）的 payload 里有顶层 ``thinking`` 字段，
客户端 ``_build_payload`` 通过调用参数 ``thinking_enabled`` 做单次覆盖：

    payload["thinking"] = {"type": "enabled" if thinking else "disabled"}

不支持的客户端（SiliconFlow / DashScope / 本地 / 通用 OpenAI）会在
``openai_compat/client.py`` 里把这个参数 pop 掉，不会泄漏进请求体，所以传了也安全。

开关随请求 ContextVar 传播（与 ``message_branch`` 的分支元数据同一套机制）：
安卓「模型」页的开关按角色存在本地，发消息时随请求体带 ``thinking`` 字段。
``None`` 表示客户端没表态，沿用后端 ``settings.model.llm.thinking_enabled``。
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Optional

_request_thinking: ContextVar[Optional[bool]] = ContextVar(
    "xiaoyou_request_thinking", default=None
)

_TRUE_WORDS = {"1", "true", "yes", "on", "enabled", "enable"}
_FALSE_WORDS = {"0", "false", "no", "off", "disabled", "disable"}


def normalize_thinking(value: Any) -> Optional[bool]:
    """把客户端传上来的各种写法归一成 True / False / None。

    None 表示「没表态」，调用方应继续用后端配置，而不是当成 False 关掉思考 ——
    老客户端不带这个字段，不能因为字段缺失就把所有人的思考模式关掉。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE_WORDS:
            return True
        if text in _FALSE_WORDS:
            return False
    return None


def set_request_thinking(value: Optional[bool]) -> Token:
    """设置当前请求的思考开关，返回用于复原的 token。"""
    return _request_thinking.set(value)


def reset_request_thinking(token: Token) -> None:
    """还原当前请求的思考开关（请求结束时必须调用，否则会串到同任务后续请求）。"""
    _request_thinking.reset(token)


def get_request_thinking() -> Optional[bool]:
    """当前请求的思考开关；None 表示调用方没指定，沿用后端配置。"""
    return _request_thinking.get()
