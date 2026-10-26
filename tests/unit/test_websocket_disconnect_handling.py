"""WebSocket 断连异常判定与 ping 响应竞态回归测试。

背景：客户端断网后仍可能有一条 ping 已在服务端排队，``handle_ping`` 回 pong 时
Starlette 抛 ``WebSocketDisconnect(1006)``（``str()`` 为空串），旧逻辑只按异常
文案判断，于是把正常的断连打成了 ERROR + 堆栈。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect, WebSocketState

from core.interfaces.websocket.adapters.fastapi import routing as routing_module
from core.interfaces.websocket.adapters.fastapi.routing import (
    WebSocketMessageRouterMixin,
)
from core.interfaces.websocket.adapters.handlers.connection_handlers import (
    ConnectionHandlers,
)
from core.interfaces.websocket.message_sending import MessageSendingMixin
from core.utils.websocket_logging import is_websocket_disconnect_error


class FakeWebSocket:
    """最小 WebSocket 替身：只实现 ping 路径用到的方法与状态字段。"""

    def __init__(self, send_error=None):
        self.application_state = WebSocketState.CONNECTED
        self.client_state = WebSocketState.CONNECTED
        self.close_code = None
        self.send_error = send_error
        self.sent = []

    async def send_json(self, payload):
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(payload)


class FakePingHandlers:
    """只实现 handle_ping 的处理器替身。"""

    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def handle_ping(self, websocket, message):
        self.calls.append(message)
        if self.error is not None:
            raise self.error


class FakeRouter(WebSocketMessageRouterMixin):
    """挂载路由 Mixin 的最小宿主，隔离掉 manager 与各领域处理器。"""

    def __init__(self, handlers):
        self.handlers = handlers
        self.websocket_manager = None
        self.streaming = SimpleNamespace()


def _connection_handlers():
    return ConnectionHandlers(SimpleNamespace(websocket_manager=None))


class TestIsWebSocketDisconnectError:
    def test_websocket_disconnect_is_recognized_by_type(self):
        """``WebSocketDisconnect`` 的文案不稳定（空串或仅错误码），必须靠类型识别。"""
        error = WebSocketDisconnect(1006)
        assert "close" not in str(error).lower()
        assert is_websocket_disconnect_error(error) is True

    def test_disconnect_hidden_in_cause_chain_is_recognized(self):
        outer = RuntimeError("send failed")
        outer.__cause__ = WebSocketDisconnect(1006)
        assert is_websocket_disconnect_error(outer) is True

    def test_close_race_runtime_error_is_recognized(self):
        error = RuntimeError('Cannot call "send" once a close message has been sent.')
        assert is_websocket_disconnect_error(error) is True

    def test_not_connected_runtime_error_is_recognized(self):
        error = RuntimeError('WebSocket is not connected. Need to call "accept" first.')
        assert is_websocket_disconnect_error(error) is True

    def test_client_disconnected_by_class_name_is_recognized(self):
        class ClientDisconnected(Exception):
            """模拟 uvicorn.protocols.utils.ClientDisconnected（不直接 import 内部模块）。"""

        assert is_websocket_disconnect_error(ClientDisconnected()) is True

    def test_regular_error_is_not_disconnect(self):
        assert is_websocket_disconnect_error(ValueError("boom")) is False

    def test_none_is_not_disconnect(self):
        assert is_websocket_disconnect_error(None) is False

    def test_self_referencing_chain_terminates(self):
        error = ValueError("loop")
        error.__cause__ = error
        assert is_websocket_disconnect_error(error) is False

    def test_sending_mixin_reuses_shared_helper(self):
        assert MessageSendingMixin()._is_disconnect_exception(WebSocketDisconnect(1006)) is True


class TestHandlePingDisconnectRace:
    def test_disconnect_during_send_is_swallowed(self):
        handlers = _connection_handlers()
        ws = FakeWebSocket(send_error=WebSocketDisconnect(1006))

        asyncio.run(handlers.handle_ping(ws, {"type": "ping", "timestamp": 1.0}))
        assert ws.sent == []

    def test_real_send_error_still_propagates(self):
        handlers = _connection_handlers()
        ws = FakeWebSocket(send_error=ValueError("boom"))

        with pytest.raises(ValueError):
            asyncio.run(handlers.handle_ping(ws, {"type": "ping"}))

    def test_normal_ping_replies_pong(self):
        handlers = _connection_handlers()
        ws = FakeWebSocket()

        asyncio.run(handlers.handle_ping(ws, {"type": "ping", "timestamp": 1.5}))
        assert ws.sent == [{"type": "pong", "timestamp": 1.5}]

    def test_closed_connection_skips_send(self):
        handlers = _connection_handlers()
        ws = FakeWebSocket()
        ws.application_state = WebSocketState.DISCONNECTED

        asyncio.run(handlers.handle_ping(ws, {"type": "ping"}))
        assert ws.sent == []


class TestProcessMessageDisconnectLogging:
    def _run_and_capture(self, monkeypatch, error):
        """跑一次 _process_message，返回被记录下来的 (error, debug) 调用。"""
        captured = {"error": [], "debug": []}
        for level in ("error", "exception"):
            monkeypatch.setattr(
                routing_module.logger,
                level,
                lambda *a, _lvl=level, **kw: captured["error"].append((_lvl, a, kw)),
            )
        monkeypatch.setattr(
            routing_module.logger, "debug", lambda *a, **kw: captured["debug"].append((a, kw))
        )

        handlers = FakePingHandlers(error=error)
        asyncio.run(FakeRouter(handlers)._process_message(FakeWebSocket(), {"type": "ping"}))
        assert handlers.calls == [{"type": "ping"}]
        return captured

    def test_disconnect_is_debug_only(self, monkeypatch):
        captured = self._run_and_capture(monkeypatch, WebSocketDisconnect(1006))
        assert captured["error"] == []
        assert captured["debug"]

    def test_real_failure_is_logged_with_type_name(self, monkeypatch):
        captured = self._run_and_capture(monkeypatch, ValueError("boom"))
        assert len(captured["error"]) == 1
        level, args, _kwargs = captured["error"][0]
        assert level == "exception"
        assert args[1] == "ValueError"
        assert args[0] % (args[1],) == "处理消息时出错：ValueError"
