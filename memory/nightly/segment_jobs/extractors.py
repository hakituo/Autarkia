"""按段提取器的注册点（v3 F3 · WP3）。

生产提取器是 ``episode.EpisodeExtractor``（C8 结论：每段一条梗概），由 ``task_runner`` 在
开关打开时经 ``ensure_default_factory`` 挂上；测试或实验可先 ``register_extractor_factory``
注入别的实现。没有可用提取器时按段作业整轮跳过，不会退化成别的行为。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .contracts import Extractor

ExtractorFactory = Callable[[dict[str, Any]], Extractor | None]

#: 进程内唯一注册点；单测由 ``tests/unit/conftest.py`` 每例重置
_factory: ExtractorFactory | None = None


def register_extractor_factory(factory: ExtractorFactory | None) -> None:
    global _factory
    _factory = factory


def reset_extractor_registry() -> None:
    register_extractor_factory(None)


def ensure_default_factory() -> None:
    """没人注册过时挂上生产提取器（每段一条梗概，C8 结论的 B 形态）；已注册的不覆盖。"""
    if _factory is None:
        from .episode import default_episode_extractor

        register_extractor_factory(default_episode_extractor)


def resolve_extractor(config: dict[str, Any]) -> Extractor | None:
    """按 nightly 配置取提取器；未注册或工厂返回空都视为「没有可用提取器」。"""
    if _factory is None:
        return None
    return _factory(config)


__all__ = [
    "ExtractorFactory",
    "ensure_default_factory",
    "register_extractor_factory",
    "reset_extractor_registry",
    "resolve_extractor",
]
