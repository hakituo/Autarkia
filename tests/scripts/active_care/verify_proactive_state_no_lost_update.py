r"""验证 proactive_state.json 的「带 scope 写」与「延迟刷盘」不再互相覆盖。

复现路径（2026-10-27 反馈「明明刚聊过，Active Care 却说上次说话在 4 天前」）：
1. 进程启动把 proactive_state 读进 ``_proactive_state_cache``（此时时间戳是旧的）；
2. 用户发消息 → ``reset_interaction_state`` 带 scope 直写文件，写入新的
   ``last_user_interaction_ts`` / ``last_proactive_replied``；
3. 同一轮回复结束 → ``on_assistant_message_sent`` / ``set_next_decision_ts`` 走
   无 scope 写，2 秒后 flush 把整份旧缓存覆盖回文件，新时间戳被抹掉。

运行：
    venv_cpu\Scripts\python.exe tests\scripts\active_care\verify_proactive_state_no_lost_update.py
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from core.services.active_care.storage.storage import ActiveCareStorage

_OLD_TS = 1_700_000_000.0
_NEW_TS = 1_700_086_400.0


class _TemporaryStorage(ActiveCareStorage):
    """把 Active Care 状态完全隔离到临时目录，避免碰真实 companion_data。"""

    def __init__(self, root: Path):
        self._test_root = root
        super().__init__()

    def _get_runtime_dir(self, scope=None) -> str:
        target = self._test_root / str(scope or self.get_runtime_scope())
        target.mkdir(parents=True, exist_ok=True)
        return str(target)

    def _get_user_sleep_state_file(self) -> str:
        target = self._test_root / "user" / self._USER_SLEEP_STATE_FILENAME
        target.parent.mkdir(parents=True, exist_ok=True)
        return str(target)


def _state_file(storage: _TemporaryStorage, scope: str) -> Path:
    return Path(storage._get_runtime_dir(scope)) / "proactive_state.json"


def _write_state(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _read_state(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


async def _cancel_flush_task(storage: _TemporaryStorage) -> None:
    task = storage._flush_task
    storage._flush_task = None
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _verify_scoped_write_survives_flush() -> None:
    """核心复现：用户交互时间戳不能被随后的无 scope 刷盘抹回旧值。"""
    with tempfile.TemporaryDirectory() as tmp:
        storage = _TemporaryStorage(Path(tmp))
        target = _state_file(storage, "aveline")
        _write_state(target, {"last_user_interaction_ts": _OLD_TS, "last_proactive_replied": False})

        cached = await storage.get_proactive_state()
        assert cached["last_user_interaction_ts"] == _OLD_TS, "前置：缓存应持有旧值"

        await storage.save_proactive_state(
            {"last_user_interaction_ts": _NEW_TS, "last_proactive_replied": True},
            scope="aveline",
        )
        await storage.save_proactive_state({"next_llm_decision_ts": _NEW_TS + 60}, immediate=True)

        persisted = _read_state(target)
        assert persisted["last_user_interaction_ts"] == _NEW_TS, persisted
        assert persisted["last_proactive_replied"] is True, persisted
        assert persisted["next_llm_decision_ts"] == _NEW_TS + 60, persisted

        fresh = await storage.get_proactive_state()
        assert fresh["last_user_interaction_ts"] == _NEW_TS, fresh


async def _verify_deferred_flush_merges_disk() -> None:
    """延迟刷盘期间对端带 scope 写入的字段，必须与本次待写字段共存。"""
    with tempfile.TemporaryDirectory() as tmp:
        storage = _TemporaryStorage(Path(tmp))
        target = _state_file(storage, "aveline")
        _write_state(target, {"last_user_interaction_ts": _OLD_TS})
        await storage.get_proactive_state()

        await storage.save_proactive_state({"last_attempt_ts": _NEW_TS})
        await _cancel_flush_task(storage)
        await storage.save_proactive_state({"last_user_interaction_ts": _NEW_TS}, scope="aveline")
        await storage._flush_pending_updates()

        persisted = _read_state(target)
        assert persisted["last_user_interaction_ts"] == _NEW_TS, persisted
        assert persisted["last_attempt_ts"] == _NEW_TS, persisted


async def _verify_pending_scope_isolation() -> None:
    """scope 切换后，旧 scope 的待写字段只能落到旧 scope 的文件。"""
    with tempfile.TemporaryDirectory() as tmp:
        storage = _TemporaryStorage(Path(tmp))
        aveline_file = _state_file(storage, "aveline")
        ling_file = _state_file(storage, "ling")

        await storage.save_proactive_state({"last_attempt_ts": _NEW_TS})
        await _cancel_flush_task(storage)
        storage.set_runtime_scope("ling")
        await storage._flush_pending_updates()

        assert _read_state(aveline_file)["last_attempt_ts"] == _NEW_TS
        assert not ling_file.exists(), "旧 scope 的待写字段不应写进新 scope"


async def _verify_read_failure_keeps_disk() -> None:
    """刷盘前读盘失败时不得用待写字段覆盖整份磁盘状态。"""
    with tempfile.TemporaryDirectory() as tmp:
        storage = _TemporaryStorage(Path(tmp))
        target = _state_file(storage, "aveline")
        _write_state(target, {"last_user_interaction_ts": _NEW_TS})

        async def _boom(_filepath):
            raise RuntimeError("read failed")

        storage._read_json_file = _boom  # type: ignore[method-assign]
        await storage.save_proactive_state({"last_attempt_ts": _NEW_TS}, immediate=True)
        await _cancel_flush_task(storage)

        assert _read_state(target) == {"last_user_interaction_ts": _NEW_TS}
        assert storage._pending_updates == {"last_attempt_ts": _NEW_TS}


async def _verify_scoped_write_reconciles_pending() -> None:
    """同 scope 还有待写字段时，带 scope 直写要把它们一起落盘。"""
    with tempfile.TemporaryDirectory() as tmp:
        storage = _TemporaryStorage(Path(tmp))
        target = _state_file(storage, "aveline")
        _write_state(target, {"last_user_interaction_ts": _OLD_TS})

        await storage.save_proactive_state({"last_attempt_ts": _NEW_TS})
        await _cancel_flush_task(storage)
        await storage.save_proactive_state({"last_user_interaction_ts": _NEW_TS}, scope="aveline")

        persisted = _read_state(target)
        assert persisted["last_user_interaction_ts"] == _NEW_TS
        assert persisted["last_attempt_ts"] == _NEW_TS


async def _verify_empty_state_keeps_disk() -> None:
    """缓存被带 scope 的写失效时，刷盘不得把磁盘文件误删。"""
    with tempfile.TemporaryDirectory() as tmp:
        storage = _TemporaryStorage(Path(tmp))
        target = _state_file(storage, "aveline")
        _write_state(target, {"last_user_interaction_ts": _NEW_TS})

        await storage.save_proactive_state({"last_attempt_ts": _NEW_TS}, scope="aveline")
        storage._dirty = True
        await storage._flush_pending_updates()

        assert _read_state(target)["last_user_interaction_ts"] == _NEW_TS


async def _main() -> None:
    await _verify_scoped_write_survives_flush()
    await _verify_deferred_flush_merges_disk()
    await _verify_pending_scope_isolation()
    await _verify_read_failure_keeps_disk()
    await _verify_scoped_write_reconciles_pending()
    await _verify_empty_state_keeps_disk()
    print("[OK] proactive_state 双写覆盖验证通过（6/6）")


if __name__ == "__main__":
    asyncio.run(_main())
