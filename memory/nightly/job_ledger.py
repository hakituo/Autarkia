"""nightly 蒸馏作业账本（v3 F4）：``pending → leased → done | skipped | failed``。

取代旧的「只看近 24h、至多 50 条」资格窗口——旧规则下失败或积压的记忆一旦
滑出 24h 就永远不再有资格，形成静默丢失。

账本只记**非 done** 状态：done 的真源是记忆本身的 ``is_distilled``（产物已落盘
才算完成），账本里不重复存一份，避免两份真相不一致。没有条目 = pending。

- ``leased``：本轮已领走；进程崩溃后租约过期自动回到 pending，不会卡死；
- ``failed``：可重试，按指数退避；达到 ``max_attempts`` 后不再自动重试，
  在 ``summary()`` 里单列 ``exhausted``，等人工处理而不是悄悄消失；
- ``skipped``：明确不适用（如正文不可用、被污染的每日总结），带原因。
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

LEDGER_VERSION = 1

STATE_LEASED = "leased"
STATE_FAILED = "failed"
STATE_SKIPPED = "skipped"

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_LEASE_SECONDS = 2 * 3600
# 一晚只跑一次，退避基数取 20h：失败的条目下一晚重试，再失败就隔两晚
DEFAULT_BACKOFF_SECONDS = 20 * 3600


class DistillJobLedger:
    """单个记忆 scope 的作业账本；``path=None`` 时只在内存里（测试/只读审计）。"""

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        extractor_version: str = "",
    ) -> None:
        self.path = Path(path) if path else None
        self.max_attempts = max(1, int(max_attempts))
        self.lease_seconds = float(lease_seconds)
        self.backoff_seconds = float(backoff_seconds)
        self.extractor_version = str(extractor_version or "")
        self._lock = threading.RLock()
        self._jobs: Dict[str, Dict[str, Any]] = self._load()

    # ---- 资格 -------------------------------------------------------------
    def is_eligible(self, job_id: str, *, now: Optional[float] = None) -> bool:
        stamp = time.time() if now is None else float(now)
        with self._lock:
            job = self._jobs.get(str(job_id))
        if job is None:
            return True
        state = job.get("state")
        if state == STATE_LEASED:
            return float(job.get("lease_expires_at") or 0.0) <= stamp
        if state == STATE_FAILED:
            if int(job.get("attempt_count") or 0) >= self.max_attempts:
                return False
            return float(job.get("retry_after") or 0.0) <= stamp
        return False  # skipped：明确不适用，不再自动领取

    # ---- 状态迁移 ---------------------------------------------------------
    def lease(self, job_ids: Iterable[str], *, now: Optional[float] = None) -> None:
        stamp = time.time() if now is None else float(now)
        with self._lock:
            for job_id in job_ids:
                job = self._jobs.setdefault(str(job_id), {})
                job.update(
                    state=STATE_LEASED,
                    leased_at=stamp,
                    lease_expires_at=stamp + self.lease_seconds,
                    extractor_version=self.extractor_version,
                )

    def mark_done(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(str(job_id), None)

    def mark_failed(self, job_id: str, error: str, *, now: Optional[float] = None) -> None:
        stamp = time.time() if now is None else float(now)
        with self._lock:
            job = self._jobs.setdefault(str(job_id), {})
            attempts = int(job.get("attempt_count") or 0) + 1
            job.update(
                state=STATE_FAILED,
                attempt_count=attempts,
                last_error=str(error or "")[:300],
                failed_at=stamp,
                retry_after=stamp + self.backoff_seconds * (2 ** (attempts - 1)),
                extractor_version=self.extractor_version,
            )
            job.pop("lease_expires_at", None)

    def mark_skipped(self, job_id: str, reason: str, *, now: Optional[float] = None) -> None:
        stamp = time.time() if now is None else float(now)
        with self._lock:
            self._jobs[str(job_id)] = {
                "state": STATE_SKIPPED,
                "skip_reason": str(reason or ""),
                "skipped_at": stamp,
                "extractor_version": self.extractor_version,
            }

    def release(self, job_ids: Iterable[str]) -> None:
        """本轮预算用完没轮到的条目：退回 pending，下一轮按原顺序继续。"""
        with self._lock:
            for job_id in job_ids:
                job = self._jobs.get(str(job_id))
                if job is None or job.get("state") != STATE_LEASED:
                    continue
                if int(job.get("attempt_count") or 0) > 0:
                    job["state"] = STATE_FAILED
                    job.pop("lease_expires_at", None)
                else:
                    self._jobs.pop(str(job_id), None)

    def forget_missing(self, live_ids: Iterable[str]) -> int:
        """记忆被删除后清掉对应条目，避免账本无界增长。"""
        live = {str(item) for item in live_ids}
        with self._lock:
            stale = [job_id for job_id in self._jobs if job_id not in live]
            for job_id in stale:
                self._jobs.pop(job_id, None)
        return len(stale)

    def forget_other_versions(self) -> int:
        """提取器换版本后，旧版本留下的 skipped / failed 条目作废，按新版本重新排队。"""
        with self._lock:
            stale = [
                job_id
                for job_id, job in self._jobs.items()
                if job.get("state") != STATE_LEASED
                and str(job.get("extractor_version") or "") != self.extractor_version
            ]
            for job_id in stale:
                self._jobs.pop(job_id, None)
        return len(stale)

    # ---- 观测 -------------------------------------------------------------
    def state_of(self, job_id: str) -> str:
        with self._lock:
            job = self._jobs.get(str(job_id))
        return str(job.get("state")) if job else "pending"

    def summary(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        skip_reasons: Dict[str, int] = {}
        exhausted = 0
        with self._lock:
            for job in self._jobs.values():
                state = str(job.get("state") or "")
                counts[state] = counts.get(state, 0) + 1
                if state == STATE_SKIPPED:
                    reason = str(job.get("skip_reason") or "")
                    skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                if state == STATE_FAILED and int(job.get("attempt_count") or 0) >= self.max_attempts:
                    exhausted += 1
        return {"states": counts, "skip_reasons": skip_reasons, "exhausted": exhausted}

    # ---- 持久化 -----------------------------------------------------------
    def save(self) -> None:
        if self.path is None:
            return
        from core.utils.atomic_io import safe_json_dump

        with self._lock:
            payload = {
                "version": LEDGER_VERSION,
                "updated_at": time.time(),
                "jobs": {key: dict(value) for key, value in sorted(self._jobs.items())},
            }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        safe_json_dump(payload, self.path)

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if self.path is None or not self.path.exists():
            return {}
        from core.utils.atomic_io import safe_json_load

        raw = safe_json_load(self.path, default={})
        jobs = raw.get("jobs") if isinstance(raw, dict) else None
        if not isinstance(jobs, dict):
            return {}
        return {str(key): dict(value) for key, value in jobs.items() if isinstance(value, dict)}


def ledger_path_for(manager: Any) -> Optional[Path]:
    """账本落在该 scope 的记忆目录下：``<memories>/nightly/<user>_distill_jobs.json``。"""
    layout = getattr(manager, "_memory_layout", None)
    history_dir = layout.get("history_dir") if isinstance(layout, dict) else None
    if not history_dir:
        return None
    user_id = str(getattr(manager, "user_id", "") or "default")
    safe_user = re.sub(r"[^0-9A-Za-z_.-]+", "_", user_id)[:120] or "default"
    return Path(history_dir) / "nightly" / f"{safe_user}_distill_jobs.json"


__all__ = [
    "STATE_FAILED",
    "STATE_LEASED",
    "STATE_SKIPPED",
    "DistillJobLedger",
    "ledger_path_for",
]
