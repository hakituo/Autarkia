"""拓扑回填共享数据模型（预览与后续 apply 共用）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class RoomNode:
    """Android Room ``messages`` 表的一行（只保留拓扑所需字段）。"""

    node_id: str
    session_id: str
    parent_id: str
    text: str
    timestamp: float
    is_user: bool
    variant_index: int
    is_active: bool
    message_type: str


@dataclass
class RoomChain:
    """同一用户轮下的一条 AI 回复变体链（多个气泡拼接后的完整正文）。"""

    root: RoomNode
    user: RoomNode
    nodes: List[RoomNode]
    text: str


@dataclass
class RoomSession:
    session_id: str
    nodes: Dict[str, RoomNode] = field(default_factory=dict)
    roots: List[str] = field(default_factory=list)
    children: Dict[str, List[str]] = field(default_factory=dict)
    chains: List[RoomChain] = field(default_factory=list)
    user_nodes: List[RoomNode] = field(default_factory=list)
    assistant_nodes: List[RoomNode] = field(default_factory=list)
    integrity: Dict[str, int] = field(default_factory=dict)
    active_path: List[str] = field(default_factory=list)

    @property
    def window_start(self) -> float:
        return min((node.timestamp for node in self.nodes.values()), default=0.0)


@dataclass
class ServerTurn:
    """服务端同一 ``message_id`` 下的一组事件（user / assistant / thought）。"""

    message_id: str
    events: List[Dict[str, Any]]
    user_events: List[Dict[str, Any]]
    assistant_events: List[Dict[str, Any]]
    system_events: List[Dict[str, Any]]
    occurred_at: float


@dataclass
class EventDecision:
    """一条服务端事件的回填结论；未配上时 ``client_node_id`` 为空。"""

    event_id: str
    conversation_id: str
    role: str
    event_type: str
    message_id: str
    occurred_at: float
    client_node_id: str = ""
    parent_node_id: str = ""
    is_root: bool = False
    match_method: str = ""
    confidence: str = ""
    reason: str = ""
    duplicate_submission: bool = False
    parent_without_event: bool = False

    @property
    def matched(self) -> bool:
        return bool(self.client_node_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "event_type": self.event_type,
            "message_id": self.message_id,
            "occurred_at": self.occurred_at,
            "client_node_id": self.client_node_id,
            "parent_node_id": self.parent_node_id,
            "is_root": self.is_root,
            "match_method": self.match_method,
            "confidence": self.confidence,
            "reason": self.reason,
            "duplicate_submission": self.duplicate_submission,
            "parent_without_event": self.parent_without_event,
        }
