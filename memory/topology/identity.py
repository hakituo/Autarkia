"""namespace / continuity 归属判定（v3 D1 / E6）。

namespace 先于一切世界线过滤，决定"这段内容归谁"；
continuity 决定"是不是同一条叙事"。两者都只做可解释判定：
认不出就返回 unknown / 会话级隔离，不猜默认角色。
"""

from __future__ import annotations

from typing import Any, Dict, List

_CONTINUITY_MARKERS = ("__persona__", "__circle__", "__scope__")


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def resolve_namespace(conversation_id: str, storage_scope: str = "") -> str:
    """namespace 先于世界线过滤：优先显式 storage_scope，其次会话 ID 注册表。"""
    if clean_text(storage_scope):
        return clean_text(storage_scope).lower()
    try:
        from core.utils.data.data_paths import resolve_data_scope_from_conversation_id

        return clean_text(resolve_data_scope_from_conversation_id(conversation_id, default=""))
    except Exception:  # noqa: BLE001 - 审计脚本允许在无配置环境下跑
        return _resolve_namespace_by_marker(conversation_id)


def _resolve_namespace_by_marker(conversation_id: str) -> str:
    cid = clean_text(conversation_id).lower()
    if not cid:
        return "unknown"
    if "__scope__" in cid:
        return cid.split("__scope__", 1)[1].strip("_").split("__", 1)[0] or "unknown"
    if "__circle__" in cid:
        token = cid.split("__circle__", 1)[1].strip("_").split("__", 1)[0]
        return token or "unknown"
    if "__persona__" in cid:
        token = cid.rsplit("__persona__", 1)[-1].strip("_").split("__", 1)[0]
        for role in ("aveline", "ling", "ye", "yeye", "rushuang", "lin", "tt"):
            if token.endswith(role) or token == role:
                return role
        return "unknown"
    return "user"


def resolve_continuity_id(conversation_id: str, namespace: str = "") -> str:
    """叙事连续性：同角色跨平台私聊共享，群聊/互聊/后台对话各自独立。

    判定顺序（与 spec §6.4 一致）：
    - ``group_*`` / ``peer_*`` / ``__circle__`` 是不同叙事（群聊、双角色互聊、
      角色后台独处），分别隔离；
    - 其余私聊按 **namespace（角色 scope）** 归一：同一角色的 QQ / Web / App
      会话共享同一条 continuity，不因 conversation 不同而自动变成不同世界线；
    - namespace 认不出时才退回按会话隔离（不猜默认角色）。

    ``continuity_mapping()`` 可导出映射清单供 §13 的人工确认使用。
    """
    cid = clean_text(conversation_id).lower()
    if not cid:
        return "continuity:unknown"
    if cid.startswith("group_") or "__group__" in cid:
        return f"continuity:conversation:{cid}"
    if "__circle__" in cid:
        token = cid.rsplit("__circle__", 1)[-1].strip("_").split("__", 1)[0]
        return f"continuity:circle:{token or 'unknown'}"
    if cid.startswith("peer_"):
        return f"continuity:peer:{cid[len('peer_'):] or 'unknown'}"
    resolved = clean_text(namespace).lower() or resolve_namespace(cid)
    if resolved and resolved != "unknown":
        return f"continuity:scope:{resolved}"
    return f"continuity:conversation:{cid}"


def continuity_mapping(conversation_ids) -> Dict[str, List[str]]:
    """导出 continuity → conversation 清单，供跨平台共享范围人工确认。"""
    mapping: Dict[str, List[str]] = {}
    for conversation_id in conversation_ids:
        cid = clean_text(conversation_id)
        if not cid:
            continue
        mapping.setdefault(resolve_continuity_id(cid), []).append(cid)
    return {key: sorted(values) for key, values in sorted(mapping.items())}
