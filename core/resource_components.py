#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源管理基础组件

本模块现在只提供三样东西：

- ``ResourcePriority`` / ``ResourceThreshold`` / ``ResourceState`` 三个类型定义
  （``core.resource.manager`` 与兼容层 ``core.resource_manager`` 都从这里取）；
- ``ModelResource``：模型资源的数据结构；
- ``_get_torch``：延迟读 ``sys.modules`` 的辅助函数。

历史沿革：本模块原先还带一个 448 行的 ``ResourceMonitor``，那是 ``core/resource/monitor.py``
重构前的旧版副本 —— 19 个共有方法已**全部漂移**，且 ``get_resource_state`` 在阈值缺失时
仍抛 ``KeyError``（新版已改为返回 ``NORMAL``）。该旧类没有任何生产调用点，已删除；
需要资源监控器请直接用 ``core.resource.monitor``。
"""

from __future__ import annotations
from core.utils.logger import get_logger


import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

import sys

from core.contracts import DeviceType, ModelRuntimeState, ResourceSeverity

logger = get_logger(__name__)


def _get_torch():
    """延迟导入 torch，避免启动时加载 2~5 秒"""
    return sys.modules.get("torch")


class ResourcePriority(Enum):
    """资源优先级枚举"""

    HIGH = 100
    MEDIUM = 50
    LOW = 10
    IDLE = 1


ResourceState = ResourceSeverity


@dataclass
class ResourceThreshold:
    """资源阈值配置"""

    warning: float
    critical: float
    emergency: float


@dataclass
class ModelResource:
    """模型资源类"""

    model_id: str
    model_type: str
    priority: ResourcePriority
    load_func: Callable
    unload_func: Callable
    memory_usage_mb: int = 0
    vram_usage_mb: int = 0
    device: str = "CPU"
    offload_func: Optional[Callable] = None
    instance: Any = None
    is_loaded: bool = False
    is_offloaded: bool = False
    last_used_time: float = field(default_factory=time.time)
    usage_count: int = 0

    def update_usage(self):
        self.last_used_time = time.time()
        self.usage_count += 1

    @property
    def runtime_state(self) -> ModelRuntimeState:
        if bool(self.is_loaded):
            if bool(self.is_offloaded):
                return ModelRuntimeState.OFFLOADED
            return ModelRuntimeState.LOADED
        return ModelRuntimeState.UNLOADED

    @property
    def device_type(self) -> DeviceType:
        device = str(self.device or "").strip().lower()
        if device in {"gpu", "cuda"}:
            return DeviceType.GPU
        if device in {"cpu"}:
            return DeviceType.CPU
        return DeviceType.UNKNOWN

    def to_contract_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_type": self.model_type,
            "priority": getattr(self.priority, "name", str(self.priority)),
            "state": self.runtime_state.value,
            "device": self.device_type.value,
            "memory_usage_mb": int(self.memory_usage_mb or 0),
            "vram_usage_mb": int(self.vram_usage_mb or 0),
            "is_loaded": bool(self.is_loaded),
            "is_offloaded": bool(self.is_offloaded),
            "last_used_time": float(self.last_used_time or 0.0),
            "usage_count": int(self.usage_count or 0),
        }
