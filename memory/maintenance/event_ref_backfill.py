"""legacy weighted 记录补写 ``event_ref`` 的迁移计划（v3 D8）。

只补元数据：不改 content / timestamp / id / summary，也不清理 legacy_only。
解析纪律与 redistill 一致 —— 宁可不动也不猜：

- 已有 ``event_ref`` 且能对上原始事件 → ``already_linked``（只校验）；
- 缺 ref / ref 失效，且 turn 级唯一命中 → ``resolved``（写入 event_ref）；
- 同 role 同 message_id 命中多条事件 → ``ambiguous``（跳过）；
- 完全没有候选 → ``legacy_only`` / ``stale_ref``（跳过，不伪称可重建）；
- 同一物理记录被重复读入 → ``duplicate_id``（跳过）。

注意：**多条记忆指向同一事件是合法 provenance**（一条长回复可派生多条记忆），
所以不把「共享来源」判冲突；冲突只针对角色不符等结构性矛盾。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from memory.maintenance.redistill_resolution import conversation_bucket

STATUS_ALREADY_LINKED = "already_linked"
STATUS_RESOLVED = "resolved"
STATUS_STALE_REF = "stale_ref"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_LEGACY_ONLY = "legacy_only"
STATUS_CONFLICT = "conflict"
STATUS_DUPLICATE_ID = "duplicate_id"
STATUS_MALFORMED = "malformed_metadata"

_EXCLUDED_DIRS = {"short_term", "long_term", "topology"}


@dataclass(frozen=True)
class RecordSource:
    """一条 weighted 记录在磁盘上的位置与解析所需的最小字段。"""

    file_path: str
    position: int
    memory_id: str
    role: str
    conversation_id: str
    message_id: str
    existing_event_id: str = ""

    @classmethod
    def from_record(
        cls, file_path: str, position: int, record: Mapping[str, Any]
    ) -> "RecordSource":
        metadata = record.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        ref = metadata.get("event_ref")
        ref = ref if isinstance(ref, dict) else {}
        return cls(
            file_path=file_path,
            position=position,
            memory_id=str(record.get("id") or f"{file_path}#{position}"),
            role=str(record.get("role") or record.get("source") or "").strip().lower(),
            conversation_id=conversation_bucket(metadata),
            message_id=str(metadata.get("message_id") or "").strip(),
            existing_event_id=str(ref.get("event_id") or "").strip(),
        )


@dataclass
class BackfillItem:
    source: RecordSource
    status: str
    target: Dict[str, Any] = field(default_factory=dict)
    detail: str = ""


@dataclass
class BackfillPlan:
    items: List[BackfillItem] = field(default_factory=list)
    blocked: bool = False
    reasons: List[str] = field(default_factory=list)

    @property
    def writable(self) -> List[BackfillItem]:
        return [item for item in self.items if item.status == STATUS_RESOLVED]

    def counts(self) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for item in self.items:
            result[item.status] = result.get(item.status, 0) + 1
        return dict(sorted(result.items()))

    def report(self) -> Dict[str, Any]:
        return {
            "blocked": self.blocked,
            "reasons": list(self.reasons),
            "counts": self.counts(),
            "denominator": len(self.items),
            "items": [
                {
                    "memory_id": item.source.memory_id,
                    "file_path": item.source.file_path,
                    "position": item.source.position,
                    "role": item.source.role,
                    "conversation_id": item.source.conversation_id,
                    "message_id": item.source.message_id,
                    "status": item.status,
                    "target_event_id": item.target.get("event_id", ""),
                    "detail": item.detail,
                }
                for item in self.items
            ],
        }


def iter_record_sources(role_data_dir: Path) -> Iterable[RecordSource]:
    """遍历 ``<scope>_data/memories`` 下的 weighted JSON（与审计口径一致）。"""
    memories_dir = Path(role_data_dir) / "memories"
    if not memories_dir.exists():
        return
    candidates = [
        path
        for path in sorted(memories_dir.rglob("*_weighted.json"))
        if not _EXCLUDED_DIRS & set(path.relative_to(memories_dir).parts[:-1])
    ]
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        records = data.get("weighted_memories") if isinstance(data, dict) else None
        if not isinstance(records, list):
            continue
        for position, record in enumerate(records):
            if isinstance(record, dict):
                yield RecordSource.from_record(str(path), position, record)


def build_backfill_plan(
    sources: Iterable[RecordSource],
    event_index: Mapping[str, Any],
) -> BackfillPlan:
    """生成整批迁移计划；解析缺口逐条标记，结构性问题才阻断整批。"""
    by_event: Mapping[str, Any] = event_index.get("by_event_detail") or {}
    by_turn: Mapping[Any, Any] = event_index.get("by_turn") or {}
    plan = BackfillPlan()
    seen_positions: Dict[Any, str] = {}

    for source in sources:
        key = (source.file_path, source.position)
        if key in seen_positions:
            plan.items.append(
                BackfillItem(
                    source,
                    STATUS_DUPLICATE_ID,
                    detail=f"同一物理记录已被 {seen_positions[key]} 读入",
                )
            )
            continue
        seen_positions[key] = source.memory_id
        plan.items.append(_resolve_source(source, by_event, by_turn))

    if not plan.items:
        plan.blocked = True
        plan.reasons.append("没有可迁移的记录")
    return plan


def _resolve_source(
    source: RecordSource,
    by_event: Mapping[str, Any],
    by_turn: Mapping[Any, Any],
) -> BackfillItem:
    if source.existing_event_id:
        detail = by_event.get(source.existing_event_id)
        if isinstance(detail, dict):
            if source.role and detail.get("role") and detail["role"] != source.role:
                return BackfillItem(
                    source,
                    STATUS_CONFLICT,
                    detail=(
                        f"现有 event_ref={source.existing_event_id} 属于 "
                        f"{detail['role']}，与记录角色 {source.role} 不符"
                    ),
                )
            return BackfillItem(source, STATUS_ALREADY_LINKED)

    if not (source.role and source.message_id):
        return BackfillItem(
            source,
            STATUS_STALE_REF if source.existing_event_id else STATUS_LEGACY_ONLY,
            detail="缺 role/message_id，无法做 turn 级解析",
        )

    candidates = _turn_candidates(source, by_turn)
    if len(candidates) > 1:
        return BackfillItem(
            source,
            STATUS_AMBIGUOUS,
            detail=f"role={source.role} message_id={source.message_id} 命中 {len(candidates)} 条事件",
        )
    if not candidates:
        return BackfillItem(
            source,
            STATUS_STALE_REF if source.existing_event_id else STATUS_LEGACY_ONLY,
            detail="没有可唯一命中的原始事件",
        )

    detail = by_event.get(candidates[0])
    if not isinstance(detail, dict):
        return BackfillItem(
            source,
            STATUS_STALE_REF if source.existing_event_id else STATUS_LEGACY_ONLY,
            detail=f"候选事件 {candidates[0]} 缺少详情",
        )
    if source.role and detail.get("role") and detail["role"] != source.role:
        return BackfillItem(
            source,
            STATUS_CONFLICT,
            detail=f"候选事件角色 {detail['role']} 与记录角色 {source.role} 不符",
        )
    return BackfillItem(
        source,
        STATUS_RESOLVED,
        target={
            "event_id": detail["event_id"],
            "conversation_id": detail.get("conversation_id", ""),
            "relative_path": detail.get("relative_path", ""),
            "role": detail.get("role", ""),
        },
    )


def _turn_candidates(source: RecordSource, by_turn: Mapping[Any, Any]) -> List[str]:
    keys = [(source.role, source.conversation_id, source.message_id)]
    if source.conversation_id:
        keys.append((source.role, "", source.message_id))
    candidates: List[str] = []
    for key in keys:
        for event_id in by_turn.get(key, ()) or ():
            event_id = str(event_id or "").strip()
            if event_id and event_id not in candidates:
                candidates.append(event_id)
    return candidates


def summarize_plan(plan: BackfillPlan) -> List[str]:
    counts = plan.counts()
    lines = [
        f"计划总数={len(plan.items)} 可写={len(plan.writable)} 阻断={plan.blocked}",
        f"分类：{counts}",
    ]
    if plan.reasons:
        lines.append(f"阻断原因：{plan.reasons}")
    return lines


__all__ = [
    "BackfillItem",
    "BackfillPlan",
    "RecordSource",
    "build_backfill_plan",
    "iter_record_sources",
    "summarize_plan",
]
