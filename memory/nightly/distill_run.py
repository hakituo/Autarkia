"""单轮蒸馏的账目编排（v3 F4）：开账本、领租约、按产物结算、退回未轮到的条目。

结算只看产物：记忆已 ``is_distilled`` 才记 done（``update_memory_distillation``
落盘成功才会置位）；批量响应缺条目、单条结果为空、写回失败一律记 failed
（可重试），不会因为「这一批跑过了」就整批当成功。
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Iterator, List, Set

from core.utils.logger import get_module_logger

from .candidates import CandidateBatch
from .job_ledger import DistillJobLedger, ledger_path_for

logger = get_module_logger(__name__, "nightly_processor.log")

#: 记在账本上的提取器版本：换 prompt / 模型时改这里，便于后续按版本重算
EXTRACTOR_VERSION = "nightly-per-memory-1"


def open_ledger(manager: Any, config: Dict[str, Any]) -> DistillJobLedger:
    ledger = getattr(manager, "_distill_job_ledger", None)
    if isinstance(ledger, DistillJobLedger):
        return ledger
    ledger = DistillJobLedger(
        ledger_path_for(manager),
        max_attempts=int(config.get("distillation_max_attempts") or 3),
        extractor_version=EXTRACTOR_VERSION,
    )
    try:
        manager._distill_job_ledger = ledger
    except Exception as exc:  # noqa: BLE001 - 只是缓存，挂不上也能用
        logger.debug("账本缓存到管理器失败（不影响本轮）: %s", exc)
    return ledger


def run_budget(config: Dict[str, Any]) -> Dict[str, float]:
    """单轮预算：条数 / 正文字符（近似 token）/ 墙钟秒数，0 表示不设该项上限。"""
    return {
        "max_items": int(config.get("max_distill_per_night") or 50),
        "max_chars": int(config.get("max_distill_chars_per_night") or 0),
        "max_seconds": float(config.get("max_distill_seconds_per_night") or 0),
    }


def _is_distilled(manager: Any, memory_id: str) -> bool:
    with manager.lock:
        memory = manager.weighted_memories.get(memory_id)
    return bool(memory and memory.get("is_distilled"))


def settle(manager: Any, ledger: DistillJobLedger, messages: Iterable[Dict[str, Any]]) -> Set[str]:
    """按产物结算一组候选，返回已结算的 ID。"""
    settled: Set[str] = set()
    for message in messages:
        memory_id = str(message.get("id") or "")
        if not memory_id:
            continue
        if _is_distilled(manager, memory_id):
            ledger.mark_done(memory_id)
        else:
            ledger.mark_failed(memory_id, "no_distillation_result")
        settled.add(memory_id)
    return settled


@contextmanager
def leased_run(
    manager: Any, ledger: DistillJobLedger, batch: CandidateBatch, budget: Dict[str, float]
) -> Iterator[RunClock]:
    """租出本轮候选；退出时把没轮到的退回 pending 并落盘账本。"""
    ids: List[str] = [str(item.get("id") or "") for item in batch.items]
    ledger.lease(ids)
    ledger.save()
    clock = RunClock(budget.get("max_seconds") or 0.0)
    try:
        yield clock
    finally:
        untouched = [item for item in ids if item not in clock.settled]
        ledger.release(untouched)
        try:
            ledger.forget_missing(_live_ids(manager))
        except Exception as exc:  # noqa: BLE001
            logger.debug("清理账本孤儿条目失败: %s", exc)
        ledger.save()
        logger.info(
            "蒸馏账目：积压=%d 本轮领取=%d 已结算=%d 退回=%d 预算外=%d 账本=%s",
            batch.backlog_total,
            len(ids),
            len(clock.settled),
            len(untouched),
            batch.deferred,
            ledger.summary(),
        )


def _live_ids(manager: Any) -> List[str]:
    with manager.lock:
        return [str(key) for key in manager.weighted_memories]


class RunClock:
    """墙钟预算；``expired`` 只在组与组之间检查，组内不打断已发出的请求。"""

    def __init__(self, max_seconds: float) -> None:
        self._deadline = time.monotonic() + max_seconds if max_seconds > 0 else None
        self.settled: Set[str] = set()

    @property
    def expired(self) -> bool:
        return self._deadline is not None and time.monotonic() >= self._deadline


__all__ = ["EXTRACTOR_VERSION", "RunClock", "leased_run", "open_ledger", "run_budget", "settle"]
