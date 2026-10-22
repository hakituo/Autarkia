"""验证 errors_20261012.json 中「asyncio.Lock 绑定到不同事件循环」的修复契约。

生产现象（SLEEP_STATE 保存用户级睡眠状态失败）：
    <asyncio.locks.Lock ... [unlocked, waiters:1]> is bound to a different event loop

根因：长生命周期单例（ActiveCareStorage._file_lock）在进程内经历事件循环重建
（服务重启 / 多次 asyncio.run）后仍复用旧锁；Python 3.10 的 Lock 只在竞争
分支校验绑定循环，旧循环残留等待者时新循环 acquire 直接抛 RuntimeError。

修复：LazyAsyncLock.acquire 比对当前运行循环，循环切换时透明重建底层锁。
"""

from __future__ import annotations

import ast
import asyncio
from contextlib import suppress
from pathlib import Path
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.utils.concurrency.async_locks import LazyAsyncLock


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _leave_stale_waiter(lock: LazyAsyncLock) -> None:
    """在旧循环里制造竞争并残留一个未取消的等待者（复现生产前置条件）。"""

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        await lock.acquire()
        waiter = asyncio.create_task(lock.acquire())
        await asyncio.sleep(0)  # 让 waiter 排队，底层锁由此绑定当前循环
        waiter.cancel()
        with suppress(asyncio.CancelledError):
            await waiter
        lock.release()
        # 模拟等待任务随旧循环异常终止，没走 CancelledError 清理
        lock._lock._waiters.append(loop.create_future())

    asyncio.run(scenario())


def verify_cross_loop_rebind() -> None:
    """同一把 LazyAsyncLock 跨事件循环复用必须透明重建，不抛跨循环错误。"""
    from core.utils.concurrency.async_locks import LazyAsyncLock

    lock = LazyAsyncLock()

    async def use_once() -> None:
        async with lock:
            await asyncio.sleep(0)

    _leave_stale_waiter(lock)
    asyncio.run(use_once())  # 修复前抛 RuntimeError: bound to a different event loop
    assert lock.locked() is False
    print("[PASS] 跨事件循环复用时 LazyAsyncLock 透明重建底层锁")


def verify_stale_locked_lock_recovers() -> None:
    """旧循环关闭时锁仍被持有（锁泄漏），新循环里也要能获取锁并告警。"""
    from core.utils.concurrency import async_locks

    warnings: list[str] = []

    class _Recorder:
        def warning(self, message: str) -> None:
            warnings.append(message)

    original_logger = async_locks.logger
    async_locks.logger = _Recorder()
    try:
        lock = async_locks.LazyAsyncLock()

        async def acquire_only() -> None:
            await lock.acquire()  # 故意不 release，模拟旧循环异常关闭

        asyncio.run(acquire_only())
        asyncio.run(lock.acquire())  # 不死锁、不抛跨循环错误
        lock.release()
    finally:
        async_locks.logger = original_logger

    assert lock.locked() is False
    assert len(warnings) == 1, f"锁泄漏应恰好告警 1 次，实际 {len(warnings)} 次"
    print("[PASS] 旧循环残留 locked 状态时重建并告警，不把死锁带进新循环")


def verify_storage_uses_lazy_lock() -> None:
    """ActiveCareStorage 的文件锁必须继续走 LazyAsyncLock（契约防回退）。"""
    storage_source = (
        PROJECT_ROOT / "core/services/active_care/storage/storage.py"
    ).read_text(encoding="utf-8")
    assert "self._file_lock = LazyAsyncLock()" in storage_source

    lock_source = (
        PROJECT_ROOT / "core/utils/concurrency/async_locks.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(lock_source)
    acquire = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "acquire"
    )
    # acquire 内必须存在「运行循环 != 绑定循环则重建」的守卫
    guard = "self._loop is not loop"
    assert guard in ast.get_source_segment(lock_source, acquire)
    print("[PASS] Storage 文件锁走 LazyAsyncLock，acquire 带循环切换重建守卫")


def main() -> int:
    verify_cross_loop_rebind()
    verify_stale_locked_lock_recovers()
    verify_storage_uses_lazy_lock()
    print("结果: 3/3 项修复契约通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
