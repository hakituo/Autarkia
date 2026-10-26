"""redistill 回写目标解析：把原始聊天事件精确映射到唯一加权记忆。

为什么需要这一层：``message_id`` 是 **turn 级** 标识，同一轮 user / assistant /
thought 三个事件共用一个值。旧实现用它当唯一键建索引（``setdefault``），
同轮的第二条消息会被静默丢弃或覆盖到别人的槽位上，预览与真实回写因此可能不一致。

本模块只做解析，且都是纯函数/快照读取：

- ``MemoryTargetIndex``：从记忆池快照建索引，按
  ``event_ref.event_id`` → ``(role, conversation_id, message_id)`` 两级解析；
- ``event_ref`` 缺失（旧数据）时只允许"全场唯一"的 turn 级匹配，且必须 role 相符；
  多于一条候选一律判 ambiguous，宁可不动也不猜。

整批计划与回滚执行见 ``redistill_apply``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

RESOLVED_BY_EVENT_REF = "event_ref"
RESOLVED_BY_TURN = "turn_unique"
STATUS_OK = "ok"
STATUS_MISSING = "missing"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_ROLE_MISMATCH = "role_mismatch"


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class SourceEvent:
    """一条待回写的原始聊天事件。"""

    event_id: str
    conversation_id: str
    role: str
    message_id: str
    content: str
    timestamp: float
    relative_path: str = ""
    storage_scope: str = ""

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SourceEvent":
        return cls(
            event_id=str(payload.get("event_id") or "").strip(),
            conversation_id=str(payload.get("conversation_id") or "").strip(),
            role=str(payload.get("role") or "").strip().lower(),
            message_id=str(payload.get("message_id") or "").strip(),
            content=str(payload.get("content") or ""),
            timestamp=_as_float(payload.get("timestamp")),
            relative_path=str(payload.get("relative_path") or "").strip(),
            storage_scope=str(payload.get("storage_scope") or "").strip(),
        )


@dataclass(frozen=True)
class TargetResolution:
    """单条事件解析出来的回写目标。"""

    memory_id: str = ""
    status: str = STATUS_MISSING
    resolved_by: str = ""
    candidate_count: int = 0
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK and bool(self.memory_id)


@dataclass
class ApplyItem:
    """计划中的一条回写项。"""

    index: int
    event: SourceEvent
    summary: str
    keywords: List[str]
    resolution: TargetResolution


@dataclass
class ApplyPlan:
    """整批回写计划；``blocked`` 为真时不得写入任何一条。"""

    items: List[ApplyItem] = field(default_factory=list)
    blocked: bool = False
    reasons: List[str] = field(default_factory=list)

    @property
    def writable(self) -> List[ApplyItem]:
        return [item for item in self.items if item.resolution.ok]


def conversation_bucket(metadata: Mapping[str, Any]) -> str:
    """从记忆元数据里取会话归属：优先 event_ref，其次相对路径文件名。"""
    event_ref = metadata.get("event_ref")
    if isinstance(event_ref, dict):
        cid = str(event_ref.get("conversation_id") or "").strip()
        if cid:
            return cid
        rel_path = str(event_ref.get("relative_path") or "").strip()
        if rel_path:
            name = rel_path.replace("\\", "/").rsplit("/", 1)[-1]
            if name.endswith(".jsonl"):
                return name[: -len(".jsonl")]
    return ""


class MemoryTargetIndex:
    """记忆池快照索引：只读，不持有管理器锁。"""

    def __init__(self, records: Optional[Mapping[str, Mapping[str, Any]]] = None) -> None:
        self._by_event_id: Dict[str, List[str]] = {}
        self._by_turn: Dict[tuple, List[str]] = {}
        self._role_by_memory: Dict[str, str] = {}
        for memory_id, record in (records or {}).items():
            self._add(str(memory_id), record)

    @classmethod
    def from_manager(cls, manager: Any) -> "MemoryTargetIndex":
        """在锁内拷出快照后再建索引，避免长期占用写锁。"""
        lock = getattr(manager, "lock", None)
        if lock is not None:
            with lock:
                snapshot = {
                    str(memory_id): dict(record)
                    for memory_id, record in (manager.weighted_memories or {}).items()
                    if isinstance(record, dict)
                }
        else:
            snapshot = {
                str(memory_id): dict(record)
                for memory_id, record in (getattr(manager, "weighted_memories", {}) or {}).items()
                if isinstance(record, dict)
            }
        return cls(snapshot)

    def _add(self, memory_id: str, record: Mapping[str, Any]) -> None:
        metadata = record.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        role = str(record.get("role") or record.get("source") or "").strip().lower()
        self._role_by_memory[memory_id] = role

        event_ref = metadata.get("event_ref")
        event_id = ""
        if isinstance(event_ref, dict):
            event_id = str(event_ref.get("event_id") or "").strip()
        if event_id:
            self._by_event_id.setdefault(event_id, []).append(memory_id)

        message_id = str(metadata.get("message_id") or "").strip()
        if role and message_id:
            key = (role, conversation_bucket(metadata), message_id)
            self._by_turn.setdefault(key, []).append(memory_id)

    @staticmethod
    def _unique(memory_ids: Iterable[str]) -> List[str]:
        seen: List[str] = []
        for memory_id in memory_ids:
            if memory_id not in seen:
                seen.append(memory_id)
        return seen

    def resolve(self, event: SourceEvent) -> TargetResolution:
        if event.event_id:
            matched = self._unique(self._by_event_id.get(event.event_id, []))
            if len(matched) == 1:
                memory_id = matched[0]
                role = self._role_by_memory.get(memory_id, "")
                if role and event.role and role != event.role:
                    return TargetResolution(
                        status=STATUS_ROLE_MISMATCH,
                        candidate_count=len(matched),
                        detail=f"event_ref={event.event_id} 属于 {role}，与事件角色 {event.role} 不符",
                    )
                return TargetResolution(
                    memory_id=memory_id,
                    status=STATUS_OK,
                    resolved_by=RESOLVED_BY_EVENT_REF,
                    candidate_count=1,
                )
            if len(matched) > 1:
                return TargetResolution(
                    status=STATUS_AMBIGUOUS,
                    candidate_count=len(matched),
                    detail=f"event_id={event.event_id} 命中 {len(matched)} 条记忆",
                )

        if not (event.role and event.message_id):
            return TargetResolution(
                status=STATUS_MISSING,
                detail="缺少 event_id 且 role/message_id 不完整",
            )

        keys = [(event.role, event.conversation_id, event.message_id)]
        if event.conversation_id:
            # 旧数据的 event_ref 可能缺 conversation_id，退一步允许空桶唯一命中
            keys.append((event.role, "", event.message_id))
        candidates: List[str] = []
        for key in keys:
            candidates.extend(self._by_turn.get(key, []))
        candidates = self._unique(candidates)
        if len(candidates) == 1:
            return TargetResolution(
                memory_id=candidates[0],
                status=STATUS_OK,
                resolved_by=RESOLVED_BY_TURN,
                candidate_count=1,
            )
        if len(candidates) > 1:
            return TargetResolution(
                status=STATUS_AMBIGUOUS,
                candidate_count=len(candidates),
                detail=(
                    f"role={event.role} message_id={event.message_id} "
                    f"conversation={event.conversation_id or '未知'} 命中 {len(candidates)} 条记忆"
                ),
            )
        return TargetResolution(
            status=STATUS_MISSING,
            detail=(
                f"没有记忆引用 event_id={event.event_id or '无'} / "
                f"role={event.role} message_id={event.message_id}"
            ),
        )
