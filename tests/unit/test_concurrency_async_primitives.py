"""core/utils/concurrency 里三个异步基础设施的单测。

覆盖：
- `async_locks.LazyAsyncLock`：懒创建、acquire/release、async with、未初始化即
  release 报错、同一循环内复用底层锁、跨事件循环自动重建（含旧锁泄漏告警）
- `async_tasks.spawn_bg_task`：引用保活、完成即清理、异常落日志、取消不报错
- `async_subprocess.run_subprocess_with_timeout`：成功返回、超时/异常均清理子进程

「禁止 flaky」的做法：
- 需要超时分支时不依赖真实时间流逝，而是把模块内的 `asyncio` 引用换成
  `_FakeAsyncio`，由它决定 `wait_for` 抛超时还是走真实实现；
- 需要「等子任务跑到某一步」时用 `asyncio.Event` 同步，而不是 `sleep(秒数)`。
- 跨事件循环用例写成同步测试、各自调一次 ``asyncio.run``（每次都是全新循环），
  精确复现单例对象在循环重建后被复用的场景，不用 sleep 卡时机。
"""

from __future__ import annotations

import asyncio
import asyncio.subprocess  # noqa: F401  确保 asyncio.subprocess 属性可用
from unittest.mock import MagicMock

import pytest

from core.utils.concurrency import async_locks, async_subprocess, async_tasks
from core.utils.concurrency.async_locks import LazyAsyncLock
from core.utils.concurrency.async_subprocess import (
    _safe_kill,
    run_subprocess_with_timeout,
)
from core.utils.concurrency.async_tasks import spawn_bg_task


async def _noop() -> None:
    return None


async def _never() -> None:
    await asyncio.Event().wait()


# ============================================================
# LazyAsyncLock
# ============================================================


class TestLazyAsyncLock:
    def test_init_does_not_create_underlying_lock(self):
        lock = LazyAsyncLock()
        assert lock._lock is None
        assert lock.locked() is False

    def test_lock_is_created_once_and_reused_within_same_loop(self):
        lock = LazyAsyncLock()

        async def use_twice():
            await lock.acquire()
            first = lock._lock
            lock.release()
            async with lock:
                assert lock._lock is first  # 同一循环内复用，不重建
                assert lock._loop is asyncio.get_running_loop()

        asyncio.run(use_twice())
        assert lock.locked() is False

    def test_lock_rebinds_after_event_loop_recreated(self):
        """同一把懒锁跨事件循环复用必须透明重建（errors_20261012 回归）。

        Python 3.10 的 Lock 只在竞争分支校验绑定循环，因此复现条件与生产
        一致：旧循环里发生过竞争（底层锁记下旧循环），且等待队列残留一个
        未取消的 Future（等待任务随旧循环异常终止，没走 CancelledError
        清理），新循环再 acquire 时旧实现抛
        "... is bound to a different event loop"。
        """
        lock = LazyAsyncLock()

        async def leave_stale_waiter() -> asyncio.AbstractEventLoop:
            loop = asyncio.get_running_loop()
            await lock.acquire()
            waiter = asyncio.create_task(lock.acquire())
            await asyncio.sleep(0)  # 让 waiter 排队，底层锁由此绑定当前循环
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            lock.release()
            # 模拟任务随旧循环异常死掉：残留一个不会被清理的等待者
            lock._lock._waiters.append(loop.create_future())
            return loop

        loop_a = asyncio.run(leave_stale_waiter())

        async def use_once() -> asyncio.AbstractEventLoop:
            async with lock:
                await asyncio.sleep(0)
            return asyncio.get_running_loop()

        loop_b = asyncio.run(use_once())
        assert loop_a is not loop_b
        assert lock._loop is loop_b
        assert lock.locked() is False

    def test_stale_locked_lock_on_loop_switch_is_rebuilt_and_warned(self, monkeypatch):
        """旧循环关闭时锁仍被持有（锁泄漏），新循环里也要能重建并告警。"""
        mock_logger = MagicMock()
        monkeypatch.setattr(async_locks, "logger", mock_logger)
        lock = LazyAsyncLock()

        async def acquire_without_release() -> asyncio.Lock:
            await lock.acquire()  # 故意不 release，模拟旧循环异常关闭导致锁泄漏
            return lock._lock

        old_lock = asyncio.run(acquire_without_release())

        async def use_after_rebind() -> None:
            async with lock:
                await asyncio.sleep(0)

        asyncio.run(use_after_rebind())  # 不死锁、不抛跨循环错误
        assert lock._lock is not old_lock
        assert lock.locked() is False
        assert mock_logger.warning.call_count == 1

    @pytest.mark.asyncio
    async def test_acquire_then_release(self):
        lock = LazyAsyncLock()
        assert await lock.acquire() is True
        assert lock.locked() is True
        lock.release()
        assert lock.locked() is False

    @pytest.mark.asyncio
    async def test_async_with_returns_self_and_releases(self):
        lock = LazyAsyncLock()
        async with lock as entered:
            assert entered is lock
            assert lock.locked() is True
        assert lock.locked() is False

    def test_release_before_init_raises(self):
        lock = LazyAsyncLock()
        with pytest.raises(RuntimeError, match="not initialized"):
            lock.release()

    @pytest.mark.asyncio
    async def test_double_release_raises_like_asyncio_lock(self):
        lock = LazyAsyncLock()
        async with lock:
            pass
        with pytest.raises(RuntimeError):
            lock.release()

    @pytest.mark.asyncio
    async def test_second_acquirer_waits_for_release(self):
        lock = LazyAsyncLock()
        entered: list[str] = []
        first_holds = asyncio.Event()
        release_first = asyncio.Event()

        async def first():
            async with lock:
                entered.append("first")
                first_holds.set()
                await release_first.wait()

        async def second():
            async with lock:
                entered.append("second")

        t1 = asyncio.create_task(first())
        await first_holds.wait()

        t2 = asyncio.create_task(second())
        # 给 second 充分的机会去抢锁；锁仍被 first 持有，它必须还在等
        for _ in range(10):
            await asyncio.sleep(0)
        assert entered == ["first"]

        release_first.set()
        await asyncio.gather(t1, t2)
        assert entered == ["first", "second"]

    def test_slots_prevents_arbitrary_attributes(self):
        lock = LazyAsyncLock()
        with pytest.raises(AttributeError):
            lock.unexpected = 1


# ============================================================
# spawn_bg_task
# ============================================================


@pytest.fixture(autouse=True)
def _isolate_pending_bg_tasks():
    """`_pending_bg_tasks` 是模块级全局集合，用例前后快照/还原避免互相污染。"""
    saved = set(async_tasks._pending_bg_tasks)
    yield
    async_tasks._pending_bg_tasks.clear()
    async_tasks._pending_bg_tasks.update(saved)


class TestSpawnBgTask:
    @pytest.mark.asyncio
    async def test_returns_task_and_cleans_up_after_done(self):
        task = spawn_bg_task(_noop(), name="w")
        assert isinstance(task, asyncio.Task)
        assert task.get_name() == "w"
        assert task in async_tasks._pending_bg_tasks

        await task
        for _ in range(3):
            await asyncio.sleep(0)
        assert task not in async_tasks._pending_bg_tasks

    @pytest.mark.asyncio
    async def test_stays_registered_while_still_running(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def work():
            started.set()
            await release.wait()

        task = spawn_bg_task(work(), name="w")
        await started.wait()
        assert task in async_tasks._pending_bg_tasks

        release.set()
        await task

    @pytest.mark.asyncio
    async def test_default_task_name_when_name_empty(self):
        task = spawn_bg_task(_noop())
        assert task.get_name().startswith("Task-")
        await task

    @pytest.mark.asyncio
    async def test_exception_is_logged_and_not_raised_to_caller(self, monkeypatch):
        mock_logger = MagicMock()
        monkeypatch.setattr(async_tasks, "logger", mock_logger)

        async def boom():
            raise ValueError("bg 失败")

        task = spawn_bg_task(boom(), name="boom-task")
        # 用 asyncio.wait 等待完成：await task 会把异常重新抛出，
        # 而这里要验证的恰恰是「异常已被 done callback 吞掉、不会冒到调用方」
        await asyncio.wait([task])
        for _ in range(3):
            await asyncio.sleep(0)

        assert mock_logger.error.call_count == 1
        logged_args = mock_logger.error.call_args.args
        assert "boom-task" in logged_args[0] % logged_args[1:]
        assert isinstance(task.exception(), ValueError)
        assert task not in async_tasks._pending_bg_tasks

    @pytest.mark.asyncio
    async def test_cancelled_task_is_not_logged_as_error(self, monkeypatch):
        mock_logger = MagicMock()
        monkeypatch.setattr(async_tasks, "logger", mock_logger)

        task = spawn_bg_task(_never(), name="c")
        for _ in range(3):
            await asyncio.sleep(0)
        task.cancel()
        # 用 asyncio.wait 等它收尾，而不是 await task：
        # 直接 await 一个已取消的任务会把 CancelledError 抛进**本测试自己的协程**，
        # 在 coverage 插桩（执行变慢、取消时机改变）下会逃出 pytest.raises 而误报。
        await asyncio.wait([task])
        for _ in range(10):
            await asyncio.sleep(0)

        assert task.cancelled() is True
        assert mock_logger.error.call_count == 0
        assert task not in async_tasks._pending_bg_tasks


# ============================================================
# run_subprocess_with_timeout / _safe_kill
# ============================================================


class _FakeProc:
    """最小子进程替身：只实现本工具用到的 communicate / kill / wait / returncode。"""

    def __init__(self, *, returncode=0, stdout=b"out", stderr=b"err"):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False
        self.waited = False

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True
        return self.returncode


class _FakeAsyncio:
    """替换模块内 `asyncio` 引用：可注入子进程、可让 wait_for 精确抛超时。

    只替换被测模块的模块级引用，不动全局 asyncio 模块，避免影响 pytest 自身。
    """

    TimeoutError = asyncio.TimeoutError
    subprocess = asyncio.subprocess

    def __init__(self, proc, *, raise_timeout=False, raise_other=None):
        self._proc = proc
        self._raise_timeout = raise_timeout
        self._raise_other = raise_other
        self.exec_args = None
        self.exec_kwargs = None

    async def create_subprocess_exec(self, *args, **kwargs):
        self.exec_args = args
        self.exec_kwargs = kwargs
        return self._proc

    async def wait_for(self, coro, timeout):
        if self._raise_timeout or self._raise_other is not None:
            coro.close()
            if self._raise_timeout:
                raise asyncio.TimeoutError()
            raise self._raise_other
        return await asyncio.wait_for(coro, timeout=timeout)


class TestRunSubprocessWithTimeout:
    @pytest.mark.asyncio
    async def test_success_returns_returncode_and_streams(self, monkeypatch):
        proc = _FakeProc(returncode=0, stdout=b"hello", stderr=b"")
        fake = _FakeAsyncio(proc)
        monkeypatch.setattr(async_subprocess, "asyncio", fake)

        rc, out, err = await run_subprocess_with_timeout(
            ["echo", "hi"], timeout=5, cwd="/tmp", env={"A": "1"}
        )

        assert (rc, out, err) == (0, b"hello", b"")
        assert proc.killed is False

    @pytest.mark.asyncio
    async def test_forwards_pipes_cwd_and_env(self, monkeypatch):
        proc = _FakeProc()
        fake = _FakeAsyncio(proc)
        monkeypatch.setattr(async_subprocess, "asyncio", fake)

        await run_subprocess_with_timeout(["ls"], timeout=5, cwd="/x", env={"K": "V"})

        assert fake.exec_args == ("ls",)
        assert fake.exec_kwargs["stdout"] is asyncio.subprocess.PIPE
        assert fake.exec_kwargs["stderr"] is asyncio.subprocess.PIPE
        assert fake.exec_kwargs["cwd"] == "/x"
        assert fake.exec_kwargs["env"] == {"K": "V"}

    @pytest.mark.asyncio
    async def test_none_returncode_becomes_minus_one(self, monkeypatch):
        proc = _FakeProc(returncode=None)
        monkeypatch.setattr(async_subprocess, "asyncio", _FakeAsyncio(proc))

        rc, _, _ = await run_subprocess_with_timeout(["x"], timeout=5)

        assert rc == -1

    @pytest.mark.asyncio
    async def test_timeout_kills_and_waits_then_reraises(self, monkeypatch):
        proc = _FakeProc(returncode=None)
        monkeypatch.setattr(async_subprocess, "asyncio", _FakeAsyncio(proc, raise_timeout=True))

        with pytest.raises(asyncio.TimeoutError):
            await run_subprocess_with_timeout(["sleep", "999"], timeout=1)

        assert proc.killed is True
        assert proc.waited is True

    @pytest.mark.asyncio
    async def test_generic_exception_also_cleans_up_process(self, monkeypatch):
        proc = _FakeProc(returncode=None)
        monkeypatch.setattr(
            async_subprocess,
            "asyncio",
            _FakeAsyncio(proc, raise_other=RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError, match="boom"):
            await run_subprocess_with_timeout(["x"], timeout=1)

        assert proc.killed is True
        assert proc.waited is True


class TestSafeKill:
    @pytest.mark.asyncio
    async def test_kills_running_process_and_waits(self):
        proc = _FakeProc(returncode=None)
        await _safe_kill(proc)
        assert proc.killed is True
        assert proc.waited is True

    @pytest.mark.asyncio
    async def test_already_exited_process_is_not_killed_but_waited(self):
        proc = _FakeProc(returncode=0)
        await _safe_kill(proc)
        assert proc.killed is False
        assert proc.waited is True

    @pytest.mark.asyncio
    async def test_process_lookup_error_is_swallowed(self):
        proc = _FakeProc(returncode=None)

        def kill():
            raise ProcessLookupError()

        proc.kill = kill
        await _safe_kill(proc)  # 不应抛
        assert proc.waited is True

    @pytest.mark.asyncio
    async def test_generic_kill_error_is_logged_and_swallowed(self, monkeypatch):
        mock_logger = MagicMock()
        monkeypatch.setattr(async_subprocess, "logger", mock_logger)
        proc = _FakeProc(returncode=None)

        def kill():
            raise OSError("kill 失败")

        proc.kill = kill
        await _safe_kill(proc)

        assert mock_logger.debug.call_count == 1
        assert proc.waited is True

    @pytest.mark.asyncio
    async def test_wait_error_is_logged_and_swallowed(self, monkeypatch):
        mock_logger = MagicMock()
        monkeypatch.setattr(async_subprocess, "logger", mock_logger)
        proc = _FakeProc(returncode=None)

        async def wait():
            raise OSError("wait 失败")

        proc.wait = wait
        await _safe_kill(proc)  # 不应抛

        assert mock_logger.debug.call_count == 1
        assert proc.killed is True
