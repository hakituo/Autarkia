"""审计报告装配：把扫描结果、权重记录与各类指标拼成机器可读结构（C1/C2/C3/C4）。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from memory.audit import metrics
from memory.audit.chat_events import ScopeScan
from memory.audit.hydration import classify_empty_memories
from memory.audit.legacy import (
    associate_records_with_events,
    build_event_index,
    orphan_event_stats,
)
from memory.audit.replay import compare_params, replay_topology
from memory.topology.events import TOPOLOGY_COMPLETE

AUDIT_SCHEMA_VERSION = "3.0"
PROJECT_TIMEZONE = "Asia/Shanghai"


def discover_scope_data_dirs(data_root: Path) -> Dict[str, Path]:
    """从 ``companion_data`` 结构反推 scope → **实际数据目录**。

    不能走 ``get_role_data_dir(scope)``：未注册进 scope registry 的角色名
    （如遗留的 chiba / kafka / rushuang）会被归一化成 ``user``，导致审计
    把 ``user_data`` 的记录重复计入多个 scope，而真正目录里的记录被漏掉。
    这里只认磁盘事实：``<name>_data`` → ``<name>``，``dual_role`` 原样保留。
    """
    found: Dict[str, Path] = {}
    if not data_root.exists():
        return found
    for entry in sorted(data_root.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "chat_history").exists():
            continue
        scope = "dual_role" if entry.name == "dual_role" else entry.name
        if scope.endswith("_data"):
            scope = scope[: -len("_data")]
        found[scope] = entry
    return found


def discover_scope_dirs(data_root: Path) -> Dict[str, Path]:
    """从 ``companion_data`` 结构反推 scope → chat_history 目录。"""
    return {
        scope: data_dir / "chat_history"
        for scope, data_dir in discover_scope_data_dirs(data_root).items()
    }


def load_weighted_records(role_data_dir: Path) -> List[Dict[str, Any]]:
    """读取 ``<scope>_data/memories`` 下的 weighted JSON（含分类子目录）。"""
    memories_dir = Path(role_data_dir) / "memories"
    records: List[Dict[str, Any]] = []
    if not memories_dir.exists():
        return records
    # 落盘布局是 memories/weighted/<category>/<user_id>_weighted.json，
    # 分类目录层数会变，必须递归找；短长期与拓扑目录不是记忆池。
    excluded = {"short_term", "long_term", "topology"}
    candidates = [
        path
        for path in memories_dir.rglob("*_weighted.json")
        if not excluded & set(path.relative_to(memories_dir).parts[:-1])
    ]
    for path in sorted(candidates):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        items = data.get("weighted_memories") if isinstance(data, dict) else None
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            record = dict(item)
            record.setdefault("id", f"{path.stem}#{index}")
            records.append(record)
    # 同一记录可能因分类迁移残留在多个分类文件里，按 id 去重
    deduped: Dict[str, Dict[str, Any]] = {}
    for record in records:
        deduped.setdefault(str(record.get("id") or ""), record)
    return list(deduped.values())


def build_scope_report(
    scope: str,
    scan: ScopeScan,
    records: Iterable[Dict[str, Any]],
    *,
    now: Optional[float] = None,
    with_replay: bool = True,
    content_by_event: Optional[Dict[str, str]] = None,
    event_index: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """``content_by_event`` / ``event_index`` 默认只看本 scope。

    跨 scope 的记忆（dual_role / peer）可能引用别的角色目录下的事件，
    调用方应传入全局索引，否则会把可回读记录误判成 event_missing。
    """
    record_list = [record for record in records if isinstance(record, dict)]
    timestamp = float(now if now is not None else time.time())
    if content_by_event is None:
        content_by_event = {
            item.normalized.event_id: item.normalized.content
            for item in scan.events
            if item.normalized.event_id
        }

    if event_index is None:
        event_index = build_event_index(scan.events)
    topology = _topology_coverage(scan)
    report: Dict[str, Any] = {
        "scope": scope,
        "chat_dir": scan.chat_dir,
        "files": scan.files,
        "lines": scan.lines,
        "malformed_lines": scan.malformed_lines,
        "events": metrics.event_distribution(scan.events),
        "pairing": metrics.complete_exchange_stats(scan.events),
        "duplicates": metrics.duplicate_stats(scan.events),
        "short_text": metrics.short_text_stats(scan.events),
        "system_markers": metrics.system_marker_stats(scan.events),
        "weights": metrics.weight_stats(record_list),
        "nightly": metrics.nightly_stats(record_list, now=timestamp),
        "hydration": classify_empty_memories(
            record_list, lambda ref: content_by_event.get(str(ref.get("event_id") or ""))
        ),
        "topology": topology,
        "legacy": associate_records_with_events(record_list, event_index),
        "orphan_events": orphan_event_stats(scan.events, record_list),
    }
    if with_replay:
        report["replay"] = replay_topology(scan.events)
        report["replay_params_compare"] = compare_params(scan.events)
    return report


def _topology_coverage(scan: ScopeScan) -> Dict[str, Any]:
    """按会话建树，输出 complete/partial/unknown 与原因计数。"""
    from collections import Counter, defaultdict

    from memory.topology.tree import build_tree

    grouped: Dict[str, List[Any]] = defaultdict(list)
    for item in scan.events:
        grouped[item.normalized.conversation_id].append(item.normalized)
    status: Counter = Counter()
    reasons: Counter = Counter()
    pending = 0
    conflicts = 0
    unknown_events = 0
    for conversation_id, events in sorted(grouped.items()):
        tree = build_tree(events, conversation_id=conversation_id)
        status[tree.topology_status] += 1
        pending += len(tree.pending)
        conflicts += len(tree.conflicts)
        unknown_events += len(tree.unknown_event_ids)
        for reason in tree.reasons:
            reasons[reason.split(" ")[0] if reason else "unknown"] += 1
    total = sum(status.values())
    return {
        "trees": total,
        "complete": status.get(TOPOLOGY_COMPLETE, 0),
        "partial": status.get("partial", 0),
        "unknown": status.get("unknown", 0),
        "complete_rate": round(status.get(TOPOLOGY_COMPLETE, 0) / total, 4) if total else None,
        "pending_nodes": pending,
        "conflicts": conflicts,
        "unknown_events": unknown_events,
        "reasons": dict(sorted(reasons.items())),
        "denominator": "按 conversation_id 建树",
    }


def summarize_report(report: Dict[str, Any]) -> List[str]:
    """人类可读摘要：全部是比率与计数，不打印正文。"""
    events = report.get("events") or {}
    pairing = report.get("pairing") or {}
    hydration = report.get("hydration") or {}
    topology = report.get("topology") or {}
    legacy = report.get("legacy") or {}
    nightly = report.get("nightly") or {}
    lines = [
        f"scope={report.get('scope')} files={report.get('files')} events={events.get('denominator')}",
        f"  成对率：{pairing.get('matched')}/{pairing.get('denominator')} = {pairing.get('rate')}",
        f"  空正文：{hydration.get('denominator')} 条 → {hydration.get('counts')}",
        f"  拓扑：trees={topology.get('trees')} complete={topology.get('complete')} "
        f"partial={topology.get('partial')} unknown={topology.get('unknown')}",
        f"  legacy：{legacy.get('counts')}，守恒={legacy.get('conservation_ok')}",
        f"  nightly：总量={nightly.get('total')} 已蒸馏={nightly.get('distilled')} "
        f"积压={nightly.get('backlog')} 超窗={nightly.get('outside_24h_window')}",
    ]
    replay = report.get("replay") or {}
    if replay:
        lines.append(
            f"  回放：段数={replay['segments']['segment_count']} "
            f"轮数={replay['segments']['turn_counts']} "
            f"不可重建树={replay['unreconstructable_trees']}"
        )
    return lines
