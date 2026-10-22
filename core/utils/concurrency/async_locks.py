"""
异步锁工具

提供 LazyAsyncLock —— 懒加载的 asyncio.Lock 包装器。

问题背景：
    Python 3.10 起 asyncio.Lock 虽然不在 __init__ 时绑定循环，但会在
    首次 acquire 时绑定当时运行的事件循环（_LoopBoundMixin），之后在
    另一个循环里复用同一把锁会抛出
    "... is bound to a different event loop"。

    长生命周期单例（如 ActiveCareStorage）在进程内经历事件循环重建
    （服务重启、多次 asyncio.run）后仍复用旧锁，就会踩到这个错误。
    LazyAsyncLock 在每次 acquire 时比对运行循环，发现循环已切换即
    透明重建底层锁；同时保留「无循环时也能实例化」的懒加载特性。

用法：
    直接替换 asyncio.Lock()：

        # 旧代码：
        self._lock = asyncio.Lock()
        async with self._lock:
            ...

        # 新代码：
        from core.utils.async_locks import LazyAsyncLock
        self._lock = LazyAsyncLock()
        async with self._lock:
            ...
"""

from __future__ import annotations

import asyncio
from typing import Optional

from core.utils.logger import get_logger

logger = get_logger(__name__)


class LazyAsyncLock:
    """懒加载且可跨事件循环复用的 asyncio.Lock 包装器。

    特性：
    - 在 __init__ 中创建实例不需要运行中的事件循环
    - 底层的 asyncio.Lock 在首次 acquire 时才真正创建
    - 运行中的事件循环切换时（进程内服务重启 / 多次 asyncio.run），
      自动重建底层锁，避免 "bound to a different event loop" 报错
    - 完全兼容 ``async with lock:`` 语法
    - 支持所有 asyncio.Lock 的方法：acquire / release / locked
    - asyncio 是单线程协作式调度，acquire 内的同步判断不会被打断，
      因此无需额外加锁即可保证重建过程只发生一次
    """

    __slots__ = ("_lock", "_loop")

    def __init__(self) -> None:
        # 不在初始化时创建 Lock，等首次使用时再创建
        # 这样可以避免在没有事件循环时创建 Lock 的问题
        self._lock: Optional[asyncio.Lock] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def acquire(self) -> bool:
        """获取锁；底层锁绑定的事件循环已切换时透明重建。"""
        loop = asyncio.get_running_loop()
        if self._lock is None or self._loop is not loop:
            if self._lock is not None and self._lock.locked():
                # 旧循环已关闭却仍持锁，说明旧锁永远不会被 release（必会死锁），
                # 只能重建；记录警告以暴露未正常释放的异常路径
                logger.warning(
                    "LazyAsyncLock 在事件循环切换时旧锁仍为 locked，"
                    "疑似旧循环异常关闭导致锁泄漏，已重建底层锁"
                )
            self._lock = asyncio.Lock()
            self._loop = loop
        return await self._lock.acquire()

    def release(self) -> None:
        """释放锁"""
        if self._lock is None:
            # 与 asyncio.Lock 的行为一致：未持有时 release 抛 RuntimeError
            raise RuntimeError("Lock is not initialized.")
        self._lock.release()

    def locked(self) -> bool:
        """返回锁是否被持有"""
        return self._lock is not None and self._lock.locked()

    async def __aenter__(self) -> "LazyAsyncLock":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


__all__ = ["LazyAsyncLock"]
