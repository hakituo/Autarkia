"""按 segment 的 nightly 作业编排（v3 F3 · WP3）。

一轮：WP1 取封口段 → 过账本资格 → ``(started_at, segment_id)`` 最旧优先 → 预算
（段数 / 字符 / 墙钟）→ ``Extractor.extract`` → 有产物写派生笔记库并结算 done；
零产出记 skipped（带原因）；异常 / 证据全越界记 failed（退避重试）；预算外退回 pending。

- **done 的真源是笔记库**（该段在当前提取器版本下有笔记），账本只记 leased / failed / skipped；
  提取器换版本后旧条目作废、段按新版本重算。
- 开关 ``segment_extraction_enabled`` 默认关，关着时不读任何数据、不调用提取器；
  ``segment_extraction_shadow`` 默认开：只写笔记库，不影响任何读路径（G 之前也没有读路径用它）。
- 白名单沿用 ``is_distillation_role_allowed``。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from core.utils.logger import get_module_logger

from .. import job_ledger
from ..config import is_distillation_role_allowed
from ..distill_run import RunClock
from ..perspective import resolve_distillation_perspective
from . import extractors, inputs
from .contracts import SKIP_UNSPECIFIED, Extractor, SegmentInput

logger = get_module_logger(__name__, "nightly_processor.log")

DONE, SKIPPED, FAILED = "done", "skipped", "failed"


def segment_ledger_path(manager: Any) -> Path | None:
    """``<memories>/nightly/<user>_segment_jobs.json``，与旧 ``_distill_jobs.json`` 分开。"""
    base = job_ledger.ledger_path_for(manager)
    if base is None:
        return None
    return base.with_name(base.name.replace("_distill_jobs.json", "_segment_jobs.json"))


def run_budget(config: Mapping[str, Any]) -> dict[str, float]:
    """单轮预算：段数 / 正文字符 / 墙钟秒数，0 表示不设该项上限。"""
    return {
        "max_segments": int(config.get("segment_max_per_night") or 0),
        "max_chars": int(config.get("segment_max_chars_per_night") or 0),
        "max_seconds": float(config.get("segment_max_seconds_per_night") or 0),
    }


def apply_budget(
    pending: Sequence[SegmentInput], budget: Mapping[str, float]
) -> list[SegmentInput]:
    """按顺序取到段数 / 字符上限为止；第一段即使超字符预算也放行，避免大段永远轮不到。"""
    picked: list[SegmentInput] = []
    used_chars = 0
    cap = int(budget.get("max_segments") or 0)
    max_chars = int(budget.get("max_chars") or 0)
    for item in pending:
        if cap and len(picked) >= cap:
            break
        if max_chars and picked and used_chars + item.char_count > max_chars:
            break
        picked.append(item)
        used_chars += item.char_count
    return picked


def accepted_versions(extractor: Any) -> set[str]:
    """当前版本 + 提取器声明「仍算完成」的旧版本（升级写法时不强制重跑已有笔记）。"""
    return {str(extractor.version), *(str(v) for v in getattr(extractor, "accepted_versions", ()))}


def _done_segments(
    store: Any, conversation_ids: Iterable[str], versions: str | set[str]
) -> dict[str, set[str]]:
    """每个会话只读一次笔记库，算出已有可接受版本笔记的段（等价于逐段 ``has_segment``）。"""
    wanted = {versions} if isinstance(versions, str) else set(versions)
    done: dict[str, set[str]] = {}
    for cid in conversation_ids:
        done[cid] = {
            str(note.get("source_segment_id") or "")
            for note in store.list_notes(cid)
            if str(note.get("extractor_version") or "") in wanted
        }
    return done


def _open_ledger(
    manager: Any, config: Mapping[str, Any], version: str
) -> job_ledger.DistillJobLedger:
    return job_ledger.DistillJobLedger(
        segment_ledger_path(manager),
        max_attempts=int(config.get("segment_max_attempts") or 3),
        extractor_version=version,
    )


def _open_note_store(scope: str, role_id: str) -> Any:
    from memory.notes import NoteStore

    return NoteStore(scope, perspective_role=role_id or scope)


def _evidence_ok(draft: Any, allowed: set[str]) -> bool:
    """F5 最小子集：证据非空，且全部落在本段来源事件内。"""
    evidence = {str(item) for item in (getattr(draft, "source_event_ids", ()) or ())}
    return bool(evidence) and evidence <= allowed


async def _process(
    item: SegmentInput,
    extractor: Extractor,
    store: Any,
    ledger: job_ledger.DistillJobLedger,
    report: dict[str, Any],
    now: float,
) -> str:
    sid = item.segment_id
    try:
        result = await extractor.extract(item)
    except Exception as exc:  # noqa: BLE001 - 解析失败 / 请求失败都可重试
        ledger.mark_failed(sid, type(exc).__name__, now=now)  # 只记类型，异常信息可能带正文
        return FAILED
    drafts = tuple(result.notes or ())
    if not drafts:
        ledger.mark_skipped(sid, result.skip_reason or SKIP_UNSPECIFIED, now=now)
        return SKIPPED
    allowed = set(item.segment.source_event_ids)
    valid = tuple(draft for draft in drafts if _evidence_ok(draft, allowed))
    report["notes_rejected"] += len(drafts) - len(valid)
    if not valid:
        ledger.mark_failed(sid, "evidence_out_of_range", now=now)
        return FAILED
    written = await asyncio.to_thread(
        store.replace_segment,
        item.conversation_id,
        sid,
        extractor.version,
        valid,
        segment_source_event_ids=tuple(item.segment.source_event_ids),
        occurred_from=item.segment.started_at,
        occurred_to=item.segment.ended_at,
    )
    report["notes_written"] += int(getattr(written, "written", 0) or 0)
    if await asyncio.to_thread(store.has_segment, item.conversation_id, sid, extractor.version):
        ledger.mark_done(sid)
        return DONE
    ledger.mark_failed(sid, "write_not_visible", now=now)
    return FAILED


async def run_segment_jobs(
    user_id: str,
    manager: Any,
    config: Mapping[str, Any],
    *,
    extractor: Extractor | None = None,
    note_store: Any = None,
    segments: Sequence[SegmentInput] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """跑一轮按段提取；返回只含计数的报告。``segments`` / ``note_store`` 供测试注入。"""
    if not config.get("segment_extraction_enabled", False):
        return {"segment_extraction": "disabled"}
    perspective = resolve_distillation_perspective(manager)
    role_id = str(perspective.get("role_id") or "")
    if not is_distillation_role_allowed(dict(config), role_id):
        return {"segment_extraction": "not_whitelisted"}
    extractor = extractor or extractors.resolve_extractor(dict(config))
    if extractor is None:
        return {"segment_extraction": "no_extractor"}
    if not config.get("segment_extraction_shadow", True):
        logger.warning("segment_extraction_shadow=false 暂无读路径接入（属 G/H），仍只写笔记库")
    scope = str(getattr(manager, "storage_scope", "") or "") or role_id
    store = note_store if note_store is not None else _open_note_store(scope, role_id)
    stamp = time.time() if now is None else float(now)
    if segments is None:
        params = inputs.SegmentParams.from_config(config)
        segments = await asyncio.to_thread(
            inputs.collect_segment_inputs, scope, params=params, now=stamp
        )
    closed = [item for item in segments if item.closed]
    ledger = _open_ledger(manager, config, extractor.version)
    ledger.forget_other_versions()
    ledger.forget_missing(item.segment_id for item in closed)
    done = await asyncio.to_thread(
        _done_segments,
        store,
        sorted({item.conversation_id for item in closed}),
        accepted_versions(extractor),
    )
    pending = [
        item
        for item in closed
        if item.segment_id not in done.get(item.conversation_id, set())
        and ledger.is_eligible(item.segment_id, now=stamp)
    ]
    pending.sort(key=lambda item: (item.segment.started_at, item.segment_id))
    budget = run_budget(config)
    picked = apply_budget(pending, budget)
    report: dict[str, Any] = {
        "segment_extraction": "ok",
        "shadow": True,
        "extractor_version": extractor.version,
        "segments_closed": len(closed),
        "pending": len(pending),
        "picked": len(picked),
        "deferred": len(pending) - len(picked),
        DONE: 0,
        SKIPPED: 0,
        FAILED: 0,
        "notes_written": 0,
        "notes_rejected": 0,
    }
    ids = [item.segment_id for item in picked]
    ledger.lease(ids, now=stamp)
    ledger.save()
    clock = RunClock(float(budget.get("max_seconds") or 0.0))
    try:
        for item in picked:
            if clock.expired:
                break
            outcome = await _process(item, extractor, store, ledger, report, stamp)
            clock.settled.add(item.segment_id)
            report[outcome] += 1
    finally:
        untouched = [sid for sid in ids if sid not in clock.settled]
        ledger.release(untouched)
        ledger.save()
        report["released"] = len(untouched)
        report["ledger"] = ledger.summary()
        logger.info("按段提取：scope=%s %s", user_id, report)
    return report


__all__ = ["apply_budget", "run_budget", "run_segment_jobs", "segment_ledger_path"]
