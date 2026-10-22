#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试重构后的 WebSocket 适配器导入。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_adapter_imports_compatible():
    """新入口与向后兼容旧入口必须导出同一实现。"""
    from core.interfaces.websocket.adapters import (
        FastAPIWebSocketAdapter,
        get_fastapi_websocket_adapter,
    )
    from core.interfaces.websocket.fastapi_websocket_adapter import (
        FastAPIWebSocketAdapter as OldAdapter,
        get_fastapi_websocket_adapter as old_get_adapter,
    )

    assert FastAPIWebSocketAdapter is OldAdapter
    assert get_fastapi_websocket_adapter is old_get_adapter


def test_env_flag_helper(monkeypatch):
    """env_flag_enabled 按环境变量取值返回布尔开关语义。"""
    from core.interfaces.websocket.adapters import env_flag_enabled

    monkeypatch.setenv("TEST_FLAG_TRUE", "1")
    monkeypatch.setenv("TEST_FLAG_FALSE", "0")
    assert env_flag_enabled("TEST_FLAG_TRUE")
    assert not env_flag_enabled("TEST_FLAG_FALSE")
    assert not env_flag_enabled("NONEXISTENT_VAR")
