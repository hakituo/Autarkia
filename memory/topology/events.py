"""规范化事件字段（v3 D1）。

原则：
- ``event_id`` 是记录标识（append 时随机 UUID），不能当幂等键；
- ``idempotency_key`` 才是重投去重键，命名空间含会话、actor、speaker 与客户端节点 ID；
- ``turn_id`` 是交互单位，user / assistant / thought 可同 turn 但各有自己的 node；
- ``content_eligible`` 只决定"能不能进提炼"（判定在 ``gating``），与拓扑保留无关。

本模块不读文件、不拿锁，全部是纯函数，方便审计脚本与单测直接调用。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping

from .gating import content_hash, is_content_eligible
from .identity import as_float, clean_text, resolve_continuity_id, resolve_namespace

SCHEMA_VERSION = "3.0"

TOPOLOGY_COMPLETE = "complete"
TOPOLOGY_PARTIAL = "partial"
TOPOLOGY_UNKNOWN = "unknown"

VISIBILITY_TREE_LOCAL = "tree_local"
VISIBILITY_CONTINUITY_LOCAL = "continuity_local"
VISIBILITY_NAMESPACE_SHARED = "namespace_shared"
VISIBILITY_LEGACY_UNKNOWN = "legacy_unknown"


@dataclass(frozen=True)
class NormalizedEvent:
    """规范化事件视图（不复制第二份原文，只承载字段契约）。"""

    event_id: str
    idempotency_key: str
    schema_version: str
    namespace: str
    perspective_role: str
    conversation_id: str
    tree_id: str
    continuity_id: str
    actor_id: str
    speaker_role: str
    turn_id: str
    event_type: str
    client_node_id: str
    parent_node_id: str
    variant_of_node_id: str
    content: str
    occurred_at: float
    recorded_at: float
    platform: str
    source_ref: Dict[str, Any] = field(default_factory=dict)
    topology_status: str = TOPOLOGY_UNKNOWN
    content_eligible: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "idempotency_key": self.idempotency_key,
            "schema_version": self.schema_version,
            "namespace": self.namespace,
            "perspective_role": self.perspective_role,
            "conversation_id": self.conversation_id,
            "tree_id": self.tree_id,
            "continuity_id": self.continuity_id,
            "actor_id": self.actor_id,
            "speaker_role": self.speaker_role,
            "turn_id": self.turn_id,
            "event_type": self.event_type,
            "client_node_id": self.client_node_id,
            "parent_node_id": self.parent_node_id,
            "variant_of_node_id": self.variant_of_node_id,
            "content": self.content,
            "occurred_at": self.occurred_at,
            "recorded_at": self.recorded_at,
            "platform": self.platform,
            "source_ref": dict(self.source_ref),
            "topology_status": self.topology_status,
            "content_eligible": self.content_eligible,
        }


def build_idempotency_key(
    *,
    conversation_id: str,
    actor_id: str,
    speaker_role: str,
    event_type: str,
    client_node_id: str = "",
    content: str = "",
    occurred_at: float = 0.0,
) -> str:
    """重投去重键。

    有客户端节点 ID 时只用稳定身份（节点 ID 本身由客户端生成），
    不把时间戳算进去 —— 同一节点重投时时间戳可能被重新赋值；
    没有客户端节点 ID 时才退回「正文哈希 + 秒级时间」这种可重复计算的组合。
    """
    parts = [
        SCHEMA_VERSION,
        clean_text(conversation_id),
        clean_text(actor_id),
        clean_text(speaker_role).lower(),
        clean_text(event_type).lower(),
    ]
    if clean_text(client_node_id):
        parts.append(f"node:{clean_text(client_node_id)}")
    else:
        parts.append(f"content:{content_hash(content)}")
        parts.append(f"ts:{int(as_float(occurred_at))}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def normalize_event(
    payload: Mapping[str, Any],
    *,
    storage_scope: str = "",
    perspective_role: str = "",
    recorded_at: float = 0.0,
    tree_id: str = "",
) -> NormalizedEvent:
    """把一条 JSONL 事件（或待写入 payload）规范化为 v3 字段。"""
    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    conversation_id = clean_text(payload.get("conversation_id")) or "default"
    role = clean_text(payload.get("role")).lower() or "system"
    event_type = clean_text(payload.get("event_type")) or "message"
    content = str(payload.get("content") or "")
    occurred_at = as_float(payload.get("timestamp") or payload.get("occurred_at"))

    client_node_id = clean_text(payload.get("client_node_id") or metadata.get("client_message_id"))
    parent_node_id = clean_text(payload.get("parent_node_id") or metadata.get("parent_id"))
    variant_of = clean_text(payload.get("variant_of_node_id") or metadata.get("variant_of"))
    turn_id = clean_text(
        payload.get("turn_id") or payload.get("message_id") or metadata.get("message_id")
    )
    platform = clean_text(payload.get("platform") or metadata.get("platform"))
    namespace = (
        clean_text(payload.get("namespace")) or resolve_namespace(conversation_id, storage_scope)
    )
    perspective = clean_text(payload.get("perspective_role")) or perspective_role or namespace

    owner_role = perspective if role in {"assistant", "system"} else "user"
    actor_id = clean_text(payload.get("actor_id")) or f"{namespace}:{owner_role}"

    if not client_node_id:
        topology_status = TOPOLOGY_UNKNOWN
    elif not parent_node_id:
        topology_status = TOPOLOGY_PARTIAL
    else:
        topology_status = TOPOLOGY_COMPLETE

    event_id = clean_text(payload.get("event_id"))
    idempotency_key = clean_text(payload.get("idempotency_key")) or build_idempotency_key(
        conversation_id=conversation_id,
        actor_id=actor_id,
        speaker_role=role,
        event_type=event_type,
        client_node_id=client_node_id,
        content=content,
        occurred_at=occurred_at,
    )

    return NormalizedEvent(
        event_id=event_id,
        idempotency_key=idempotency_key,
        schema_version=SCHEMA_VERSION,
        namespace=namespace,
        perspective_role=perspective,
        conversation_id=conversation_id,
        tree_id=clean_text(tree_id),
        continuity_id=clean_text(payload.get("continuity_id"))
        or resolve_continuity_id(conversation_id, namespace),
        actor_id=actor_id,
        speaker_role=role,
        turn_id=turn_id,
        event_type=event_type,
        client_node_id=client_node_id,
        parent_node_id=parent_node_id,
        variant_of_node_id=variant_of,
        content=content,
        occurred_at=occurred_at,
        recorded_at=as_float(payload.get("recorded_at")) or recorded_at,
        platform=platform,
        source_ref={
            "kind": "event",
            "event_id": event_id,
            "conversation_id": conversation_id,
        },
        topology_status=topology_status,
        content_eligible=is_content_eligible(content, event_type=event_type),
    )


def enrich_payload(
    payload: Mapping[str, Any],
    *,
    storage_scope: str = "",
    perspective_role: str = "",
    recorded_at: float = 0.0,
) -> Dict[str, Any]:
    """返回要合并进 JSONL payload 的 v3 字段（不改动原有字段）。"""
    event = normalize_event(
        payload,
        storage_scope=storage_scope,
        perspective_role=perspective_role,
        recorded_at=recorded_at,
    )
    return {
        "schema_version": event.schema_version,
        "idempotency_key": event.idempotency_key,
        "namespace": event.namespace,
        "continuity_id": event.continuity_id,
        "actor_id": event.actor_id,
        "turn_id": event.turn_id,
        "client_node_id": event.client_node_id,
        "parent_node_id": event.parent_node_id,
        "variant_of_node_id": event.variant_of_node_id,
        "occurred_at": event.occurred_at,
        "recorded_at": event.recorded_at,
        "platform": event.platform,
        "topology_status": event.topology_status,
        "content_eligible": event.content_eligible,
    }
