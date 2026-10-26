"""Nightly 蒸馏候选收集：公平消费全部积压（v3 F4）。

旧规则「冷却期外 + 近 24h 内 + 至多 50 条」会让失败和积压一旦滑出 24h
就永远失去资格。现在：

- 资格 = 未蒸馏 + 冷却期外 + 账本允许（未租出 / 退避到期 / 未判 skipped）；
- 顺序 = ``(timestamp, id)`` 从旧到新，稳定可复现，旧任务不会饥饿；
- 预算 = 条数上限 + 正文字符上限（近似 token 预算），超出部分留给下一轮；
- 正文为空（compact 后无法回读）或被污染的每日总结显式记 ``skipped``，
  不再被「短内容直接落盘」路径悄悄标成已蒸馏。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.services.journal.summary_guard import is_polluted_daily_summary_memory
from core.utils.logger import get_module_logger

from .job_ledger import DistillJobLedger

logger = get_module_logger(__name__, "nightly_processor.log")

SKIP_EMPTY_CONTENT = "empty_content"
SKIP_POLLUTED_SUMMARY = "polluted_daily_summary"


@dataclass
class CandidateBatch:
    """本轮领到的候选与积压账目。"""

    items: List[Dict[str, Any]] = field(default_factory=list)
    backlog_total: int = 0
    deferred: int = 0
    newly_skipped: Dict[str, int] = field(default_factory=dict)

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)


def _memory_id(message: Dict[str, Any]) -> str:
    return str(message.get("id") or "")


def collect_candidates(
    manager: Any,
    threshold_ts: float,
    max_distill: int,
    *,
    ledger: Optional[DistillJobLedger] = None,
    max_chars: int = 0,
    now: Optional[float] = None,
) -> CandidateBatch:
    """在锁内收集本轮要蒸馏的加权记忆（按最旧优先，受条数/字符预算约束）。"""
    book = ledger or DistillJobLedger()
    eligible: List[Dict[str, Any]] = []
    skipped: Dict[str, int] = {}
    with manager.lock:
        snapshot = list(manager.weighted_memories.values())
    for message in snapshot:
        memory_id = _memory_id(message)
        timestamp = float(message.get("timestamp", 0) or 0)
        if not memory_id or message.get("is_distilled") or timestamp >= threshold_ts:
            continue
        if not book.is_eligible(memory_id, now=now):
            continue
        reason = ""
        if not str(message.get("content") or "").strip():
            reason = SKIP_EMPTY_CONTENT
        elif is_polluted_daily_summary_memory(message):
            reason = SKIP_POLLUTED_SUMMARY
        if reason:
            book.mark_skipped(memory_id, reason, now=now)
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        eligible.append(message)

    eligible.sort(key=lambda item: (float(item.get("timestamp", 0) or 0), _memory_id(item)))
    picked: List[Dict[str, Any]] = []
    used_chars = 0
    cap = max(0, int(max_distill or 0))
    for message in eligible:
        if cap and len(picked) >= cap:
            break
        length = len(str(message.get("content") or ""))
        if max_chars and picked and used_chars + length > max_chars:
            break
        picked.append(message)
        used_chars += length

    if skipped:
        logger.info("蒸馏候选显式跳过：%s", skipped)
    return CandidateBatch(
        items=picked,
        backlog_total=len(eligible),
        deferred=len(eligible) - len(picked),
        newly_skipped=skipped,
    )
