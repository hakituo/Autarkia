"""``WebSocketManager.remove_connection`` 必须真正关闭 socket。

回归背景：广播发送失败时只把连接从注册表删掉、不 close，客户端会一直以为
自己在线（收不到推送但继续发 ping），弱网下长期留下 ESTAB/FIN-WAIT 半开连接。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from starlette.websockets import WebSocketState

from core.interfaces.websocket.connection import ClientConnection
from core.interfaces.websocket.connection_management import ConnectionManagementMixin


class FakeWebSocket:
    """只实现 remove_connection 用到的状态字段与 close。"""

    def __init__(self, *, closed: bool = False, close_error: BaseException | None = None):
        state = WebSocketState.DISCONNECTED if closed else WebSocketState.CONNECTED
        self.application_state = state
        self.client_state = state
        self.close_code = 1006 if closed else None
        self.close_error = close_error
        self.close_calls: list[tuple[int, str]] = []

    async def close(self, code: int = 1000, reason: str | None = None):
        if self.close_error is not None:
            raise self.close_error
        self.close_calls.append((code, reason or ""))


class Host(ConnectionManagementMixin):
    """挂载连接管理 Mixin 的最小宿主。"""

    def __init__(self):
        self.connections = {}
        self.user_connections = defaultdict(list)
        self.connections_lock = asyncio.Lock()
        self.stats = {"active_connections": 0}


def _register(host: Host, websocket: FakeWebSocket, user_id: str = "mobile_user"):
    conn = ClientConnection(websocket=websocket, user_id=user_id, platform="android")
    host.connections[websocket] = conn
    host.user_connections[user_id].append(conn)
    return conn


def test_live_connection_is_closed_on_remove():
    host = Host()
    ws = FakeWebSocket()
    _register(host, ws)

    asyncio.run(host.remove_connection(ws))

    assert ws not in host.connections
    assert "mobile_user" not in host.user_connections
    assert ws.close_calls == [(1001, "connection removed")]


def test_already_closed_connection_is_not_closed_again():
    host = Host()
    ws = FakeWebSocket(closed=True)
    _register(host, ws)

    asyncio.run(host.remove_connection(ws))

    assert ws not in host.connections
    assert ws.close_calls == []


def test_close_failure_does_not_break_removal():
    host = Host()
    ws = FakeWebSocket(close_error=RuntimeError("boom"))
    _register(host, ws)

    asyncio.run(host.remove_connection(ws))

    assert ws not in host.connections
    assert host.stats["active_connections"] == 0


def test_unknown_websocket_is_noop():
    host = Host()
    ws = FakeWebSocket()

    asyncio.run(host.remove_connection(ws))

    assert ws.close_calls == []
    assert host.connections == {}
