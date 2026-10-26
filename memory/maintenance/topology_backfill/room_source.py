"""只读读取 Android Room SQLite，并还原用户轮与 AI 回复链。

输入是 adb 拉下来的 ``aveline_database``（连同 ``-wal`` / ``-shm``）。
这里不依赖 Android 框架，只认 Room ``messages`` 表的列。
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

from .model import RoomChain, RoomNode, RoomSession

_REQUIRED_COLUMNS = {
    "id",
    "sessionId",
    "parentId",
    "text",
    "timestamp",
    "isUser",
    "variantIndex",
    "isActiveVariant",
    "messageType",
}


def _load_nodes(db_path: Path, session_prefix: str) -> Dict[str, List[RoomNode]]:
    uri = f"file:{Path(db_path).resolve()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        columns = {row[1] for row in con.execute("PRAGMA table_info(messages)")}
        missing = _REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"messages 表缺少列: {sorted(missing)}")
        rows = con.execute(
            "SELECT id, sessionId, parentId, text, timestamp, isUser, "
            "variantIndex, isActiveVariant, messageType FROM messages"
        ).fetchall()
    finally:
        con.close()

    grouped: Dict[str, List[RoomNode]] = defaultdict(list)
    for row in rows:
        session_id = str(row["sessionId"] or "")
        if not session_id.startswith(session_prefix):
            continue
        grouped[session_id].append(
            RoomNode(
                node_id=str(row["id"] or ""),
                session_id=session_id,
                parent_id=str(row["parentId"] or ""),
                text=str(row["text"] or ""),
                timestamp=float(row["timestamp"] or 0.0) / 1000.0,
                is_user=bool(row["isUser"]),
                variant_index=int(row["variantIndex"] or 0),
                is_active=bool(row["isActiveVariant"]),
                message_type=str(row["messageType"] or "text"),
            )
        )
    return dict(grouped)


def _integrity(session: RoomSession) -> Dict[str, int]:
    nodes = session.nodes
    missing = sum(
        1 for node in nodes.values() if node.parent_id and node.parent_id not in nodes
    )
    roots = sum(1 for node in nodes.values() if not node.parent_id)

    cycles: Set[str] = set()
    for node in nodes.values():
        seen: Set[str] = set()
        current = node.parent_id
        while current:
            if current in seen:
                cycles.add(node.node_id)
                break
            seen.add(current)
            parent = nodes.get(current)
            current = parent.parent_id if parent else ""

    groups: Dict[Tuple[str, bool], List[RoomNode]] = defaultdict(list)
    for node in nodes.values():
        groups[(node.parent_id, node.is_user)].append(node)
    multi = [group for group in groups.values() if len(group) > 1]
    bad_active = sum(
        1 for group in multi if sum(1 for node in group if node.is_active) != 1
    )
    bad_variant = sum(
        1
        for group in multi
        if sorted(node.variant_index for node in group) != list(range(len(group)))
    )

    return {
        "nodes": len(nodes),
        "roots": roots,
        "missing_parent": missing,
        "cycles": len(cycles),
        "sibling_groups": len(multi),
        "bad_active_groups": bad_active,
        "bad_variant_index": bad_variant,
    }


def _build_chains(session: RoomSession) -> List[RoomChain]:
    children = session.children
    chains: List[RoomChain] = []
    for user in sorted(session.user_nodes, key=lambda node: (node.timestamp, node.node_id)):
        variant_roots = [
            session.nodes[child_id]
            for child_id in children.get(user.node_id, [])
            if not session.nodes[child_id].is_user
        ]
        variant_roots.sort(
            key=lambda node: (node.variant_index, node.timestamp, node.node_id)
        )
        for root in variant_roots:
            chain_nodes = [root]
            seen = {root.node_id}
            current = root
            while True:
                kids = [
                    session.nodes[child_id]
                    for child_id in children.get(current.node_id, [])
                    if not session.nodes[child_id].is_user
                ]
                if len(kids) != 1:
                    break
                nxt = kids[0]
                if nxt.node_id in seen:
                    break
                chain_nodes.append(nxt)
                seen.add(nxt.node_id)
                current = nxt
            chains.append(
                RoomChain(
                    root=root,
                    user=user,
                    nodes=chain_nodes,
                    text="\n".join(
                        node.text for node in chain_nodes if node.text.strip()
                    ),
                )
            )
    return chains


def _active_path(session: RoomSession) -> List[str]:
    if not session.roots:
        return []
    path: List[str] = []
    seen: Set[str] = set()
    current = session.roots[0]
    while current and current not in seen:
        seen.add(current)
        path.append(current)
        kids = [session.nodes[child_id] for child_id in session.children.get(current, [])]
        if not kids:
            break
        active_kids = [kid for kid in kids if kid.is_active]
        if len(active_kids) == 1:
            current = active_kids[0].node_id
            continue
        # 手机端偶发「同层没有 / 多个激活版本」：不在这里截断，改选子树里最近
        # 有活动的分支（用户最后在那条线上继续聊），并计数供审计
        candidates = active_kids or kids
        latest = {kid.node_id: _latest_activity(session, kid.node_id) for kid in candidates}
        current = max(candidates, key=lambda kid: (latest[kid.node_id], kid.node_id)).node_id
        session.integrity["active_path_fallbacks"] = (
            session.integrity.get("active_path_fallbacks", 0) + 1
        )
    return path


def _latest_activity(session: RoomSession, node_id: str) -> float:
    """子树内最晚的消息时间（迭代遍历，避免长会话递归过深）。"""
    latest = 0.0
    stack = [node_id]
    seen: Set[str] = set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        node = session.nodes.get(current)
        if node is not None:
            latest = max(latest, node.timestamp)
        stack.extend(session.children.get(current, []))
    return latest


def load_room_sessions(
    db_path: Path,
    *,
    session_prefix: str = "web_role_",
) -> Dict[str, RoomSession]:
    """读取 Room 库并返回 ``session_id -> RoomSession``。

    只读打开；调用方负责在 adb 拉库时同时带上 ``-wal`` / ``-shm``。
    """
    grouped = _load_nodes(Path(db_path), session_prefix)
    sessions: Dict[str, RoomSession] = {}
    for session_id, nodes in grouped.items():
        node_map = {node.node_id: node for node in nodes}
        children: Dict[str, List[str]] = defaultdict(list)
        for node in nodes:
            children[node.parent_id].append(node.node_id)
        session = RoomSession(
            session_id=session_id,
            nodes=node_map,
            roots=sorted(
                (node.node_id for node in nodes if not node.parent_id),
                key=lambda node_id: (node_map[node_id].timestamp, node_id),
            ),
            children=dict(children),
            user_nodes=sorted(
                (node for node in nodes if node.is_user),
                key=lambda node: (node.timestamp, node.node_id),
            ),
            assistant_nodes=sorted(
                (node for node in nodes if not node.is_user),
                key=lambda node: (node.timestamp, node.node_id),
            ),
        )
        session.integrity = _integrity(session)
        session.chains = _build_chains(session)
        session.active_path = _active_path(session)
        sessions[session_id] = session
    return sessions


__all__ = ["load_room_sessions"]
