"""``core/resource_components.py`` 单元测试。

本模块现在只剩 ``ResourcePriority`` / ``ResourceThreshold`` / ``ResourceState`` /
``ModelResource`` 与 ``_get_torch`` —— 原先那个 448 行的旧版 ``ResourceMonitor``
（``core/resource/monitor.py`` 重构前的副本）已删除，监控器的测试见
``tests/unit/test_resource_monitor.py``。

设计原则（与 ``tests/unit/test_resource_monitor.py`` 保持一致）：

- 绝不触发真实 GPU / CUDA / NVML / nvidia-smi / 真实子进程；
- 不使用 ``sleep``，不依赖真实当前时间（用固定 ``time.time`` 桩）；
- 只断言「注入的桩值被正确读出 / 计算」，不断言真实内存、显存、耗时等易变数值。
"""

from __future__ import annotations

import sys
import types

import pytest

from core.contracts import DeviceType, ModelRuntimeState, ResourceSeverity
from core.resource_components import (
    ModelResource,
    ResourcePriority,
    ResourceState,
    ResourceThreshold,
    _get_torch,
)


def _fake_time(now):
    """固定 time.time 返回值。"""
    return types.SimpleNamespace(time=lambda: now)


# ==================== 基础：枚举 / 阈值 ====================


def test_resource_priority_enum_values():
    """ResourcePriority 各档位取值固定。"""
    assert ResourcePriority.HIGH.value == 100
    assert ResourcePriority.MEDIUM.value == 50
    assert ResourcePriority.LOW.value == 10
    assert ResourcePriority.IDLE.value == 1


def test_resource_state_alias_is_severity():
    """ResourceState 是 ResourceSeverity 的别名。"""
    assert ResourceState is ResourceSeverity
    assert ResourceState.NORMAL.value == "normal"


def test_resource_threshold_fields():
    """ResourceThreshold 三档阈值可读。"""
    th = ResourceThreshold(10.0, 20.0, 30.0)
    assert (th.warning, th.critical, th.emergency) == (10.0, 20.0, 30.0)


# ==================== _get_torch ====================


def test_get_torch_reflects_sys_modules(monkeypatch):
    """_get_torch 直接读 sys.modules，不做真实 import。"""
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    assert _get_torch() is None

    fake_torch = types.SimpleNamespace(name="fake-torch")
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert _get_torch() is fake_torch


# ==================== ModelResource ====================


def _make_model(**kwargs):
    """构造一个最小可用的 ModelResource。"""
    params = dict(
        model_id="m1",
        model_type="llm",
        priority=ResourcePriority.MEDIUM,
        load_func=lambda: "loaded",
        unload_func=lambda: None,
    )
    params.update(kwargs)
    return ModelResource(**params)


def test_model_resource_update_usage(monkeypatch):
    """update_usage 刷新时间戳并累加计数。"""
    monkeypatch.setattr("core.resource_components.time", _fake_time(1234.0))
    model = _make_model()
    model.usage_count = 3
    model.update_usage()
    assert model.last_used_time == 1234.0
    assert model.usage_count == 4


@pytest.mark.parametrize(
    "is_loaded, is_offloaded, expected",
    [
        (False, False, ModelRuntimeState.UNLOADED),
        (False, True, ModelRuntimeState.UNLOADED),
        (True, False, ModelRuntimeState.LOADED),
        (True, True, ModelRuntimeState.OFFLOADED),
    ],
)
def test_model_resource_runtime_state(is_loaded, is_offloaded, expected):
    """runtime_state 由 is_loaded / is_offloaded 组合决定。"""
    model = _make_model(is_loaded=is_loaded, is_offloaded=is_offloaded)
    assert model.runtime_state is expected


@pytest.mark.parametrize(
    "device, expected",
    [
        ("gpu", DeviceType.GPU),
        ("CUDA", DeviceType.GPU),
        ("  Cpu ", DeviceType.CPU),
        ("cpu", DeviceType.CPU),
        ("tpu", DeviceType.UNKNOWN),
        ("", DeviceType.UNKNOWN),
        (None, DeviceType.UNKNOWN),
    ],
)
def test_model_resource_device_type(device, expected):
    """device_type 归一化大小写与空白后映射到 DeviceType。"""
    model = _make_model(device=device)
    assert model.device_type is expected


def test_model_resource_to_contract_dict_with_enum_priority():
    """to_contract_dict 使用枚举名作为 priority。"""
    model = _make_model(
        priority=ResourcePriority.HIGH,
        memory_usage_mb=100,
        vram_usage_mb=200,
        device="gpu",
        is_loaded=True,
        is_offloaded=True,
        last_used_time=5.0,
        usage_count=7,
    )
    d = model.to_contract_dict()
    assert d == {
        "model_id": "m1",
        "model_type": "llm",
        "priority": "HIGH",
        "state": "offloaded",
        "device": "gpu",
        "memory_usage_mb": 100,
        "vram_usage_mb": 200,
        "is_loaded": True,
        "is_offloaded": True,
        "last_used_time": 5.0,
        "usage_count": 7,
    }


def test_model_resource_to_contract_dict_with_plain_priority_and_none_fields():
    """priority 非枚举时退化为 str；None 数值字段规整为 0。"""
    model = _make_model(priority="custom", memory_usage_mb=None, vram_usage_mb=None)
    model.last_used_time = None
    model.usage_count = None
    d = model.to_contract_dict()
    assert d["priority"] == "custom"
    assert d["memory_usage_mb"] == 0
    assert d["vram_usage_mb"] == 0
    assert d["last_used_time"] == 0.0
    assert d["usage_count"] == 0
    assert d["state"] == "unloaded"
    assert d["device"] == "cpu"
