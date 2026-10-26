"""redistill 回写执行：先整批出计划，再原子写盘，失败即回滚（B1）。

解析逻辑在 ``redistill_resolution``（两级解析 + 宁可不动也不猜）。
本模块只负责执行纪律：

- ``build_apply_plan``：任一事件解析不出唯一目标 → 整批阻断；
- ``apply_plan``：中途任何一条失败 → 用写入前快照恢复全部字段，不留半批。

``SourceEvent`` / ``MemoryTargetIndex`` 等在这里 re-export，
旧调用方（脚本与测试）继续从本模块导入。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from .redistill_resolution import (  # noqa: F401  (re-export)
    RESOLVED_BY_EVENT_REF,
    RESOLVED_BY_TURN,
    STATUS_AMBIGUOUS,
    STATUS_MISSING,
    STATUS_OK,
    STATUS_ROLE_MISMATCH,
    ApplyItem,
    ApplyPlan,
    MemoryTargetIndex,
    SourceEvent,
    TargetResolution,
)


def build_apply_plan(
    index: MemoryTargetIndex,
    events: List[SourceEvent],
    summaries: Mapping[int, Any],
) -> ApplyPlan:
    """按批次生成回写计划；任一事件解析失败即整批阻断。"""
    plan = ApplyPlan()
    for position, event in enumerate(events, start=1):
        entry = summaries.get(position)
        summary, keywords = entry if entry else ("", [])
        summary_text = str(summary or "").strip()
        resolution = index.resolve(event)
        if not summary_text:
            resolution = TargetResolution(
                status=STATUS_MISSING,
                detail="本批该条目没有解析出梗概",
            )
        plan.items.append(
            ApplyItem(
                index=position,
                event=event,
                summary=summary_text,
                keywords=[str(item).strip() for item in (keywords or []) if str(item).strip()],
                resolution=resolution,
            )
        )
        if not resolution.ok:
            plan.blocked = True
            plan.reasons.append(f"条目{position}: {resolution.status} ({resolution.detail})")

    writable = plan.writable
    if len({item.resolution.memory_id for item in writable}) != len(writable):
        # 两条事件指向同一条记忆 = 解析键仍然不够细，禁止互相覆盖
        plan.blocked = True
        plan.reasons.append("多条事件解析到同一条记忆，拒绝互相覆盖")
    return plan


def apply_plan(manager: Any, plan: ApplyPlan) -> Dict[str, Any]:
    """整批写入；中途失败则回滚已写入的字段并报告。"""
    if plan.blocked:
        return {
            "committed": False,
            "updated": 0,
            "reasons": list(plan.reasons),
            "items": [_item_report(item) for item in plan.items],
        }

    writable = plan.writable
    if not writable:
        return {"committed": True, "updated": 0, "reasons": [], "items": []}

    memory_ids = [item.resolution.memory_id for item in writable]
    snapshot = _snapshot_records(manager, memory_ids)
    if snapshot is None:
        return {
            "committed": False,
            "updated": 0,
            "reasons": ["记忆池快照失败，未写入"],
            "items": [_item_report(item) for item in plan.items],
        }

    updated = 0
    for item in writable:
        try:
            ok = bool(
                manager.update_memory_distillation(
                    item.resolution.memory_id,
                    item.summary,
                    item.keywords,
                )
            )
        except Exception as exc:  # noqa: BLE001
            ok = False
            plan.reasons.append(f"条目{item.index}: 写入异常 {type(exc).__name__}: {exc}")
        if not ok:
            _restore_records(manager, snapshot)
            plan.reasons.append(f"条目{item.index}: update_memory_distillation 返回 False")
            return {
                "committed": False,
                "updated": 0,
                "reasons": list(plan.reasons),
                "items": [_item_report(item) for item in plan.items],
            }
        updated += 1
    return {
        "committed": True,
        "updated": updated,
        "reasons": [],
        "items": [_item_report(item) for item in plan.items],
    }


def _snapshot_records(manager: Any, memory_ids: List[str]) -> Mapping[str, Dict[str, Any]] | None:
    from memory.core.lock_utils import get_write_lock

    fields = ("summary", "search_keywords", "keywords", "display_tags", "is_distilled")
    snapshot: Dict[str, Dict[str, Any]] = {}
    with get_write_lock(manager):
        for memory_id in memory_ids:
            record = (manager.weighted_memories or {}).get(memory_id)
            if not isinstance(record, dict):
                return None
            snapshot[memory_id] = {
                key: (list(record.get(key) or []) if isinstance(record.get(key), list) else record.get(key))
                for key in fields
            }
    return snapshot


def _restore_records(manager: Any, snapshot: Mapping[str, Mapping[str, Any]]) -> None:
    from memory.core.lock_utils import get_write_lock

    with get_write_lock(manager):
        for memory_id, fields in snapshot.items():
            record = (manager.weighted_memories or {}).get(memory_id)
            if not isinstance(record, dict):
                continue
            for key, value in fields.items():
                record[key] = list(value) if isinstance(value, list) else value
            mark_dirty = getattr(manager, "_mark_keyword_index_dirty_locked", None)
            if callable(mark_dirty):
                mark_dirty(memory_id)
    schedule_save = getattr(manager, "_schedule_save", None)
    if callable(schedule_save):
        schedule_save()


def _item_report(item: ApplyItem) -> Dict[str, Any]:
    return {
        "index": item.index,
        "event_id": item.event.event_id,
        "conversation_id": item.event.conversation_id,
        "role": item.event.role,
        "message_id": item.event.message_id,
        "memory_id": item.resolution.memory_id,
        "status": item.resolution.status,
        "resolved_by": item.resolution.resolved_by,
        "candidate_count": item.resolution.candidate_count,
        "detail": item.resolution.detail,
        "summary": item.summary,
    }
