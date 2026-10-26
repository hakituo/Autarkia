"""WebSocket 传输日志降噪与断连异常判定。"""

from __future__ import annotations

import logging
from typing import Optional

import websockets
import websockets.exceptions  # websockets>=11 需显式导入，否则属性访问会 AttributeError
from starlette.websockets import WebSocketDisconnect

# 连接已断开的文本信号（部分 RuntimeError 不带具体异常类型，只能靠文案识别）
_DISCONNECT_SIGNALS = (
    "keepalive ping timeout",
    "no close frame received",
    "close message has been sent",
    "connection closed",
    "client disconnected",
    "websocket is not connected",
    # Starlette/uvicorn 在连接已关闭（close 已发送或响应已完成）后再 send 抛的 RuntimeError
    "unexpected asgi message",
    "after sending 'websocket.close'",
    "response already completed",
)


def _find_windows_error(error: Optional[BaseException], winerror: int) -> bool:
    """沿异常链查找指定 Windows 错误码。"""
    seen: set[int] = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "winerror", None) == winerror:
            return True
        current = current.__cause__ or current.__context__
    return False


def _is_single_disconnect_error(error: BaseException | None) -> bool:
    """判断单个异常（不追链）是否表示客户端已断开。"""
    if error is None:
        return False
    if isinstance(
        error,
        (
            websockets.exceptions.ConnectionClosed,
            WebSocketDisconnect,
            ConnectionError,
            BrokenPipeError,
        ),
    ):
        return True
    # uvicorn.protocols.utils.ClientDisconnected 不宜直接 import（内部模块），按类名识别
    if error.__class__.__name__ == "ClientDisconnected":
        return True
    error_message = str(error).lower()
    return any(signal in error_message for signal in _DISCONNECT_SIGNALS)


def is_websocket_disconnect_error(error: BaseException | None) -> bool:
    """沿异常链判断是否为客户端断开导致的异常。

    ``starlette.websockets.WebSocketDisconnect`` 的 ``str()`` 是空串，
    只按异常文案判断会把它当成真实错误打出 ERROR 日志与堆栈。
    """
    seen: set[int] = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if _is_single_disconnect_error(current):
            return True
        current = current.__cause__ or current.__context__
    return False


class RecoverableWebSocketDisconnectFilter(logging.Filter):
    """把 Windows 读超时断连转换为无堆栈的可恢复信息日志。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "recoverable_websocket_disconnect", False):
            return True
        if record.getMessage() != "data transfer failed":
            return True
        error = record.exc_info[1] if record.exc_info else None
        if not _find_windows_error(error, 121):
            return True

        record.levelno = logging.INFO
        record.levelname = "INFO"
        record.msg = "WebSocket 客户端读取超时（WinError 121），连接已清理并等待客户端重连"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        record.recoverable_websocket_disconnect = True
        return True
