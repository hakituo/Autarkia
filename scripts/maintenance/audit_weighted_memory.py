#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""加权记忆只读审计：事件分布、成对率、重复、空正文 hydration、拓扑覆盖、legacy 关联。

口径（每项都写在报告里）：分母、过滤条件、去重键、快照时间、时区。
只读：不写记忆池、不改 JSONL；hydration 用本次扫描到的事件正文做内存回读，
不触发 SQLite 索引重建。

运行：
    venv_cpu\\Scripts\\python.exe scripts\\maintenance\\audit_weighted_memory.py
    venv_cpu\\Scripts\\python.exe scripts\\maintenance\\audit_weighted_memory.py --scope aveline --out output\\evaluation\\audit.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.utils.data.data_paths import get_companion_data_dir  # noqa: E402
from core.utils.time.time_utils import get_current_time  # noqa: E402
from memory.audit.chat_events import scan_scope  # noqa: E402
from memory.audit.legacy import build_event_index  # noqa: E402
from memory.audit.report import (  # noqa: E402
    AUDIT_SCHEMA_VERSION,
    PROJECT_TIMEZONE,
    build_scope_report,
    discover_scope_data_dirs,
    discover_scope_dirs,
    load_weighted_records,
    summarize_report,
)


def _aggregate(scopes: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    totals = {
        "scopes": len(scopes),
        "events": 0,
        "trees": 0,
        "complete_trees": 0,
        "legacy_only": 0,
        "hydration_empty": 0,
        "nightly_backlog": 0,
    }
    for report in scopes.values():
        totals["events"] += int((report.get("events") or {}).get("denominator") or 0)
        topology = report.get("topology") or {}
        totals["trees"] += int(topology.get("trees") or 0)
        totals["complete_trees"] += int(topology.get("complete") or 0)
        totals["legacy_only"] += int(
            ((report.get("legacy") or {}).get("counts") or {}).get("legacy_only") or 0
        )
        totals["hydration_empty"] += int(
            (report.get("hydration") or {}).get("denominator") or 0
        )
        totals["nightly_backlog"] += int((report.get("nightly") or {}).get("backlog") or 0)
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(description="加权记忆只读审计")
    parser.add_argument("--scope", action="append", default=[], help="只审计指定 scope，可重复")
    parser.add_argument("--data-root", default="", help="companion_data 根目录，默认自动解析")
    parser.add_argument("--out", default="", help="报告输出路径（默认 output/evaluation/）")
    parser.add_argument("--no-replay", action="store_true", help="跳过 topology/segment 回放")
    args = parser.parse_args()

    started = time.time()
    data_root = Path(args.data_root) if args.data_root else Path(get_companion_data_dir())
    data_dirs = discover_scope_data_dirs(data_root)
    scope_dirs = discover_scope_dirs(data_root)
    requested: List[str] = [str(item).strip() for item in args.scope if str(item).strip()]
    if requested:
        missing = [scope for scope in requested if scope not in scope_dirs]
        for scope in missing:
            chat_dir = data_root / f"{scope}_data" / "chat_history"
            if chat_dir.exists():
                scope_dirs[scope] = chat_dir
                data_dirs[scope] = chat_dir.parent
        wanted = set(requested)
        scope_dirs = {scope: path for scope, path in scope_dirs.items() if scope in wanted}
        data_dirs = {scope: path for scope, path in data_dirs.items() if scope in wanted}

    if not scope_dirs:
        print(f"[空] {data_root} 下没有可审计的 chat_history 目录")
        return 0

    scans = {
        scope: scan_scope(scope, chat_dir)
        for scope, chat_dir in sorted(scope_dirs.items())
    }
    # 跨 scope 索引：dual_role / peer 记忆可能引用别的角色目录下的事件
    global_content: Dict[str, str] = {}
    global_events: List[Any] = []
    for scan in scans.values():
        for item in scan.events:
            if item.normalized.event_id:
                global_content[item.normalized.event_id] = item.normalized.content
            global_events.append(item)
    global_index = build_event_index(global_events)

    reports: Dict[str, Dict[str, Any]] = {}
    for scope, scan in scans.items():
        records = load_weighted_records(data_dirs[scope])
        reports[scope] = build_scope_report(
            scope,
            scan,
            records,
            with_replay=not args.no_replay,
            content_by_event=global_content,
            event_index=global_index,
        )

    now = get_current_time()
    payload = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "generated_at": now.isoformat(timespec="seconds"),
        "timezone": PROJECT_TIMEZONE,
        "data_root": str(data_root),
        "totals": _aggregate(reports),
        "scopes": reports,
        "elapsed_seconds": round(time.time() - started, 2),
    }

    out_path = (
        Path(args.out)
        if args.out
        else Path("output") / "evaluation" / f"weighted_memory_audit_{now:%Y%m%d_%H%M%S}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[审计] {payload['generated_at']}（{PROJECT_TIMEZONE}）")
    for report in reports.values():
        for line in summarize_report(report):
            print(line)
    print(f"\n[汇总] {json.dumps(payload['totals'], ensure_ascii=False)}")
    print(f"[报告] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
