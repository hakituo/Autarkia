#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""D8 迁移：给 legacy weighted 记录补写 event_ref（默认 dry-run）。

只补元数据，不改内容 / 时间 / ID；无法唯一关联的记录逐条标记并跳过。
必须在服务停止时运行（运行中的 manager 可能用旧快照覆盖回写）。

    venv_cpu\\Scripts\\python.exe scripts\\maintenance\\backfill_event_refs.py
    venv_cpu\\Scripts\\python.exe scripts\\maintenance\\backfill_event_refs.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.utils.data.data_paths import get_companion_data_dir  # noqa: E402
from core.utils.time.time_utils import get_current_time, now_iso  # noqa: E402
from memory.audit.chat_events import scan_scope  # noqa: E402
from memory.audit.legacy import build_event_index  # noqa: E402
from memory.audit.report import (  # noqa: E402
    build_scope_report,
    discover_scope_data_dirs,
    discover_scope_dirs,
    load_weighted_records,
)
from memory.maintenance.event_ref_apply import apply_backfill_plan  # noqa: E402
from memory.maintenance.event_ref_backfill import (  # noqa: E402
    build_backfill_plan,
    iter_record_sources,
    summarize_plan,
)


def _scan_all(scope_dirs: Dict[str, Path]):
    scans = {scope: scan_scope(scope, path) for scope, path in sorted(scope_dirs.items())}
    texts: Dict[str, str] = {}
    events: List[Any] = []
    for scan in scans.values():
        for item in scan.events:
            events.append(item)
            if item.normalized.event_id:
                texts[item.normalized.event_id] = item.normalized.content
    return scans, texts, events


def _all_sources(data_dirs: Iterable[Path]):
    for data_dir in data_dirs:
        yield from iter_record_sources(Path(data_dir))


def _summarize_scopes(reports: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    totals = {"events": 0, "trees": 0, "complete": 0, "partial": 0, "unknown": 0}
    legacy: Dict[str, int] = {}
    for report in reports.values():
        totals["events"] += int((report.get("events") or {}).get("denominator") or 0)
        topology = report.get("topology") or {}
        for key in ("trees", "complete", "partial", "unknown"):
            totals[key] += int(topology.get(key) or 0)
        for key, value in ((report.get("legacy") or {}).get("counts") or {}).items():
            legacy[key] = legacy.get(key, 0) + int(value or 0)
    totals["legacy"] = dict(sorted(legacy.items()))
    return totals


def _report_scopes(scans, texts, data_dirs, event_index) -> Dict[str, Dict[str, Any]]:
    reports: Dict[str, Dict[str, Any]] = {}
    for scope, scan in scans.items():
        records = load_weighted_records(Path(data_dirs[scope]))
        reports[scope] = build_scope_report(
            scope,
            scan,
            records,
            with_replay=False,
            content_by_event=texts,
            event_index=event_index,
        )
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description="legacy weighted event_ref 回填")
    parser.add_argument("--scope", action="append", default=[], help="只处理指定 scope，可重复")
    parser.add_argument("--data-root", default="", help="companion_data 根目录，默认自动解析")
    parser.add_argument("--apply", action="store_true", help="实际写盘（缺省只出计划）")
    parser.add_argument("--plan-out", default="", help="计划报告输出路径")
    parser.add_argument("--backup-dir", default="", help="--apply 时的备份目录")
    args = parser.parse_args()

    started = time.time()
    data_root = Path(args.data_root) if args.data_root else Path(get_companion_data_dir())
    data_dirs = discover_scope_data_dirs(data_root)
    scope_dirs = discover_scope_dirs(data_root)
    requested = [str(item).strip() for item in args.scope if str(item).strip()]
    if requested:
        wanted = set(requested)
        scope_dirs = {scope: path for scope, path in scope_dirs.items() if scope in wanted}
        data_dirs = {scope: path for scope, path in data_dirs.items() if scope in wanted}
    if not scope_dirs:
        print(f"[空] {data_root} 下没有可处理的 chat_history 目录")
        return 0

    scans, texts, events = _scan_all(scope_dirs)
    before_index = build_event_index(events)
    before = _summarize_scopes(
        _report_scopes(scans, texts, data_dirs, before_index)
    )

    plan = build_backfill_plan(_all_sources(data_dirs.values()), before_index)
    print(f"[计划] {now_iso()}")
    for line in summarize_plan(plan):
        print(f"  {line}")
    print(f"  迁移前 legacy 关联：{before['legacy']}")

    stamp = get_current_time().strftime("%Y%m%d_%H%M%S")
    plan_out = Path(args.plan_out) if args.plan_out else (
        Path("output") / "evaluation" / f"event_ref_backfill_plan_{stamp}.json"
    )
    plan_out.parent.mkdir(parents=True, exist_ok=True)
    plan_out.write_text(
        json.dumps(plan.report(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[报告] {plan_out}")

    if not args.apply:
        print("\n[dry-run] 未写盘；确认计划后加 --apply 再跑。")
        return 0
    if plan.blocked:
        print("\n[中止] 计划被阻断，未写盘。")
        return 1

    backup_dir = Path(args.backup_dir) if args.backup_dir else (
        Path("output") / "evaluation" / f"event_ref_backfill_backup_{stamp}"
    )
    result = apply_backfill_plan(plan, backup_dir=backup_dir)
    print(f"\n[写入] committed={result['committed']} updated={result['updated']} "
          f"files={result['files']} reasons={result['reasons']}")
    if not result["committed"]:
        return 1
    print(f"[备份] {backup_dir}")

    after_scans, after_texts, after_events = _scan_all(scope_dirs)
    after_index = build_event_index(after_events)
    after = _summarize_scopes(
        _report_scopes(after_scans, after_texts, data_dirs, after_index)
    )
    print(f"[守恒] 迁移后 legacy 关联：{after['legacy']}")
    topology_keys = ("events", "trees", "complete", "partial", "unknown")
    conserved = all(before[key] == after[key] for key in topology_keys)
    expected = {
        "linked_event_ref": before["legacy"].get("linked_event_ref", 0) + result["updated"],
        "linked_turn_only": max(
            0, before["legacy"].get("linked_turn_only", 0) - result["updated"]
        ),
    }
    print(f"[守恒] 拓扑 {topology_keys} = {conserved}，预期关联增量 {expected}")
    print(f"[耗时] {round(time.time() - started, 2)}s")
    return 0 if conserved else 1


if __name__ == "__main__":
    raise SystemExit(main())
