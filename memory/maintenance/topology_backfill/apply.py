"""把配对计划落成旁挂拓扑覆盖文件（不改写原始事件）。

覆盖文件格式见 ``memory/topology/overlay.py``。写入前若已有同名文件，先复制到
备份目录；写入用原子替换，失败不留半截文件。默认只收高置信度配对。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.utils.time.time_utils import now_iso
from memory.topology import overlay as overlay_store
from memory.topology.overlay import OVERLAY_VERSION

from .plan import BackfillPlan, SessionPlan

HIGH = "high"
MEDIUM = "medium"


@dataclass
class OverlayResult:
    conversation_id: str
    path: str
    nodes: int
    events: int
    skipped_low_confidence: int
    active_leaf: str
    backup: str = ""
    written: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class ApplyReport:
    results: List[OverlayResult] = field(default_factory=list)

    def totals(self) -> Dict[str, int]:
        return {
            "sessions": len(self.results),
            "nodes": sum(item.nodes for item in self.results),
            "events": sum(item.events for item in self.results),
            "skipped_low_confidence": sum(item.skipped_low_confidence for item in self.results),
            "written": sum(1 for item in self.results if item.written),
        }


def build_overlay(
    conversation_id: str,
    session_plan: SessionPlan,
    *,
    confidences: Iterable[str] = (HIGH,),
    source: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """手机整棵树作拓扑真源；只收允许置信度的事件配对。"""
    allowed = {str(item) for item in confidences}
    session = session_plan.session
    nodes = {
        node.node_id: [node.parent_id, round(node.timestamp, 3), bool(node.is_user)]
        for node in session.nodes.values()
        if node.node_id
    }
    events: Dict[str, str] = {}
    skipped = 0
    for decision in session_plan.decisions:
        if not decision.matched:
            continue
        if decision.confidence not in allowed or decision.client_node_id not in nodes:
            skipped += 1
            continue
        events[decision.event_id] = decision.client_node_id
    return {
        "version": OVERLAY_VERSION,
        "conversation_id": conversation_id,
        "storage_scope": session_plan.storage_scope,
        "generated_at": now_iso(),
        "source": dict(source or {"kind": "android_room"}),
        "confidences": sorted(allowed),
        "active_leaf": session.active_path[-1] if session.active_path else "",
        "skipped_low_confidence": skipped,
        "nodes": nodes,
        "events": events,
    }


def apply_plan(
    plan: BackfillPlan,
    *,
    confidences: Iterable[str] = (HIGH,),
    dry_run: bool = True,
    backup_dir: Optional[Path] = None,
    source: Optional[Dict[str, Any]] = None,
) -> ApplyReport:
    report = ApplyReport()
    allowed = tuple(confidences)
    for conversation_id, session_plan in sorted(plan.sessions.items()):
        overlay = build_overlay(conversation_id, session_plan, confidences=allowed, source=source)
        # 运行时经模块取路径：测试可以把落点整体重定向到临时目录
        path = overlay_store.overlay_path(conversation_id, session_plan.storage_scope)
        result = OverlayResult(
            conversation_id=conversation_id,
            path=str(path),
            nodes=len(overlay["nodes"]),
            events=len(overlay["events"]),
            skipped_low_confidence=int(overlay["skipped_low_confidence"]),
            active_leaf=str(overlay["active_leaf"]),
        )
        if not dry_run:
            result.backup = _backup(path, backup_dir)
            _write(path, overlay)
            result.written = True
        report.results.append(result)
    if not dry_run:
        overlay_store.clear_overlay_cache()
    return report


def _backup(path: Path, backup_dir: Optional[Path]) -> str:
    if not path.exists() or backup_dir is None:
        return ""
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / path.name
    shutil.copy2(path, target)
    return str(target)


def _write(path: Path, overlay: Dict[str, Any]) -> None:
    from core.utils.atomic_io import safe_json_dump

    path.parent.mkdir(parents=True, exist_ok=True)
    safe_json_dump(overlay, path)


__all__ = ["HIGH", "MEDIUM", "ApplyReport", "OverlayResult", "apply_plan", "build_overlay"]
