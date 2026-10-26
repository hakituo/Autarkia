"""
验证脚本: 客户端断连不再刷 ERROR 日志（ping → pong 竞态）

背景：errors_20261023.json 里两条 ERROR 都来自 ``websocket/adapters/fastapi/routing.py``
的 ``_process_message``——客户端断网后仍有一条 ping 在服务端排队，``handle_ping``
回 pong 时 Starlette 抛 ``WebSocketDisconnect(1006)``（或 uvicorn 的
``ClientDisconnected``）。旧逻辑只按异常文案判断，空消息被判成真实错误，
打出「处理消息时出错：」+ 完整堆栈。

验证项：
1. 断连类异常（WebSocketDisconnect / 异常链里的 ClientDisconnected）被正确识别
2. handle_ping 在 send 阶段遇到断连时静默跳过，不抛异常、不写 ERROR
3. handle_ping 正常路径仍回 pong
4. _process_message 遇到断连只记 DEBUG，不产生 ERROR/堆栈
5. 真实异常仍然按 ERROR + 堆栈记录（降噪不吞真错）
"""

import asyncio
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from starlette.websockets import WebSocketDisconnect, WebSocketState

from core.interfaces.websocket.adapters.fastapi import routing as routing_module
from core.interfaces.websocket.adapters.fastapi.routing import (
    WebSocketMessageRouterMixin,
)
from core.interfaces.websocket.adapters.handlers import (
    connection_handlers as connection_handlers_module,
)
from core.interfaces.websocket.adapters.handlers.connection_handlers import (
    ConnectionHandlers,
)
from core.utils.websocket_logging import is_websocket_disconnect_error


class _CaptureHandler(logging.Handler):
    """只收集记录，不输出。"""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def count_at_error(self):
        return len([r for r in self.records if r.levelno >= logging.ERROR])


class _FakeWebSocket:
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


class _FailingHandlers:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    async def handle_ping(self, websocket, message):
        self.calls += 1
        raise self.error


class _Router(WebSocketMessageRouterMixin):
    """只挂载路由 Mixin 的最小宿主。"""

    def __init__(self, handlers):
        self.handlers = handlers
        self.websocket_manager = None
        self.streaming = SimpleNamespace()


def _capture(module):
    """临时替换模块 logger 为独立采集器，避免真实 ERROR 落到 errors_*.json。"""
    logger = logging.getLogger(f"verify.ping_noise.{module.__name__}")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    handler = _CaptureHandler()
    logger.addHandler(handler)
    original = module.logger
    module.logger = logger
    return handler, lambda: setattr(module, "logger", original)


def _handlers():
    return ConnectionHandlers(SimpleNamespace(websocket_manager=None))


def check_helper_recognizes_disconnect() -> list:
    """场景1: 断连异常识别（含异常链、类名兜底）。"""
    issues = []
    if not is_websocket_disconnect_error(WebSocketDisconnect(1006)):
        issues.append("[异常识别] WebSocketDisconnect 未被识别为断连")

    outer = RuntimeError("send failed")
    outer.__cause__ = WebSocketDisconnect(1006)
    if not is_websocket_disconnect_error(outer):
        issues.append("[异常识别] 异常链里的 WebSocketDisconnect 未被识别")

    class ClientDisconnected(Exception):
        """模拟 uvicorn.protocols.utils.ClientDisconnected。"""

    if not is_websocket_disconnect_error(ClientDisconnected()):
        issues.append("[异常识别] ClientDisconnected 未被识别为断连")
    if is_websocket_disconnect_error(ValueError("boom")):
        issues.append("[异常识别] 普通异常被误判为断连")
    return issues


def check_ping_disconnect_is_silent() -> list:
    """场景2: pong 发送撞上断连时静默跳过，日志不出现 ERROR。"""
    monitor, restore = _capture(connection_handlers_module)
    issues = []
    try:
        ws = _FakeWebSocket(send_error=WebSocketDisconnect(1006))
        try:
            asyncio.run(_handlers().handle_ping(ws, {"type": "ping", "timestamp": 1.0}))
        except Exception as exc:  # noqa: BLE001 - 脚本要把异常收敛成一条问题项
            issues.append(f"[ping 断连] handle_ping 不应抛异常，实际抛出 {type(exc).__name__}")
        if ws.sent:
            issues.append("[ping 断连] 连接已断时不应记录 pong 发送")
        if monitor.count_at_error():
            issues.append(f"[ping 断连] 不应写 ERROR，实际 {monitor.count_at_error()} 条")
    finally:
        restore()
    return issues


def check_ping_normal_replies_pong() -> list:
    """场景3: 正常 ping 仍回 pong（降噪不误伤）。"""
    monitor, restore = _capture(connection_handlers_module)
    issues = []
    try:
        ws = _FakeWebSocket()
        asyncio.run(_handlers().handle_ping(ws, {"type": "ping", "timestamp": 1.5}))
        if ws.sent != [{"type": "pong", "timestamp": 1.5}]:
            issues.append(f"[ping 正常] 应回 pong，实际发送 {ws.sent}")
        if monitor.count_at_error():
            issues.append("[ping 正常] 正常路径不应写 ERROR")
    finally:
        restore()
    return issues


def check_process_message_disconnect_is_debug() -> list:
    """场景4: 路由层遇到断连只记 DEBUG，无 ERROR 记录。"""
    monitor, restore = _capture(routing_module)
    issues = []
    try:
        router = _Router(_FailingHandlers(WebSocketDisconnect(1006)))
        asyncio.run(router._process_message(_FakeWebSocket(), {"type": "ping"}))
        if monitor.count_at_error():
            issues.append(f"[路由断连] 不应写 ERROR，实际 {monitor.count_at_error()} 条")
        if not [r for r in monitor.records if r.levelno == logging.DEBUG]:
            issues.append("[路由断连] 应留下 DEBUG 记录便于排查")
    finally:
        restore()
    return issues


def check_process_message_real_error_still_logs() -> list:
    """场景5: 真实异常仍然 ERROR + 堆栈。"""
    monitor, restore = _capture(routing_module)
    issues = []
    try:
        router = _Router(_FailingHandlers(ValueError("boom")))
        asyncio.run(router._process_message(_FakeWebSocket(), {"type": "ping"}))
        if monitor.count_at_error() != 1:
            issues.append(f"[真实错误] 应记录 1 条 ERROR，实际 {monitor.count_at_error()} 条")
        elif not monitor.records[-1].exc_info:
            issues.append("[真实错误] ERROR 记录应带堆栈（exc_info）")
    finally:
        restore()
    return issues


def main() -> int:
    checks = [
        ("断连异常识别", check_helper_recognizes_disconnect),
        ("ping 断连静默跳过", check_ping_disconnect_is_silent),
        ("ping 正常回 pong", check_ping_normal_replies_pong),
        ("路由断连只记 DEBUG", check_process_message_disconnect_is_debug),
        ("真实错误仍记 ERROR", check_process_message_real_error_still_logs),
    ]

    all_issues = []
    for name, check in checks:
        try:
            issues = check()
        except Exception as exc:  # noqa: BLE001 - 脚本入口统一收敛异常
            issues = [f"执行异常: {type(exc).__name__}: {exc}"]
        status = "PASS" if not issues else "FAIL"
        print(f"[{status}] {name}")
        for issue in issues:
            print(f"    - {issue}")
        all_issues.extend(issues)

    if all_issues:
        print(f"\n验证失败，共 {len(all_issues)} 项问题")
        return 1
    print("\n全部通过：断连不再刷 ERROR，真实异常仍在 ERROR + 堆栈中可见")
    return 0


if __name__ == "__main__":
    sys.exit(main())
