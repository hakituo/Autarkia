#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""预览：用 Android Room 消息树回填服务端事件的客户端节点字段。

默认只读预览。``--apply`` 只写旁挂覆盖文件
``<scope>_data/memories/topology/overlays/<会话>.json``（只含 ID 与时间戳），
不改写任何原始聊天事件；删除覆盖文件即回退。默认只收高置信度配对。

    venv_cpu/bin/python scripts/maintenance/backfill_topology_from_room.py \
        --db companion_data/backups/aveline_room_20261026/aveline_database [--apply]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.utils.data.data_paths import get_companion_data_dir  # noqa: E402
from core.utils.time.time_utils import get_current_time  # noqa: E402
from memory.audit.chat_events import iter_jsonl  # noqa: E402
from memory.audit.report import discover_scope_data_dirs  # noqa: E402
from memory.maintenance.topology_backfill import (  # noqa: E402
    BackfillPlan,
    build_plan,
    load_room_sessions,
)


def _load_server_events(
    data_root: Path, conversations: set[str]
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[str]]]:
    events: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    scopes: Dict[str, List[str]] = defaultdict(list)
    for scope, data_dir in sorted(discover_scope_data_dirs(data_root).items()):
        chat_dir = data_dir / "chat_history"
        if not chat_dir.exists():
            continue
        for path in sorted(chat_dir.rglob("*.jsonl")):
            for _number, payload in iter_jsonl(path):
                if not payload:
                    continue
                conversation_id = str(payload.get("conversation_id") or "")
                if conversation_id not in conversations:
                    continue
                events[conversation_id].append(payload)
                scopes[conversation_id].append(
                    str(payload.get("storage_scope") or scope)
                )
    return dict(events), dict(scopes)


def _print_table(plan: BackfillPlan) -> None:
    header = (
        f"{'会话':<24}{'节点':>7}{'用户':>7}{'回复链':>7}"
        f"{'窗口内':>8}{'可配':>8}{'覆盖率':>8}{'未配':>7}{'重复':>6}{'断父':>6}"
    )
    print(header)
    print("-" * len(header))
    reasons: Counter = Counter()
    for conversation_id, session_plan in sorted(plan.sessions.items()):
        counts = session_plan.counts()
        session = session_plan.session
        print(
            f"{conversation_id:<24}"
            f"{len(session.nodes):>7}"
            f"{len(session.user_nodes):>7}"
            f"{len(session.chains):>7}"
            f"{counts['in_window']:>8}"
            f"{counts['matched_in_window']:>8}"
            f"{counts['coverage_in_window'] * 100:>7.1f}%"
            f"{counts['unmatched']:>7}"
            f"{counts['duplicate_submissions']:>6}"
            f"{counts['parent_without_event_nodes']:>6}"
        )
        reasons.update(counts["reasons"])
    totals = plan.totals()
    print("-" * len(header))
    print(
        f"{'合计':<24}"
        f"{sum(len(s.session.nodes) for s in plan.sessions.values()):>7}"
        f"{sum(len(s.session.user_nodes) for s in plan.sessions.values()):>7}"
        f"{sum(len(s.session.chains) for s in plan.sessions.values()):>7}"
        f"{totals['in_window']:>8}"
        f"{totals['matched_in_window']:>8}"
        f"{totals['coverage_in_window'] * 100:>7.1f}%"
        f"{totals['unmatched']:>7}"
        f"{totals['duplicate_submissions']:>6}"
        f"{totals['parent_without_event_nodes']:>6}"
    )
    print(
        f"窗口外事件（早于手机首条消息，不能从该库恢复）: {totals['before_window']}"
    )
    print(f"未配原因: {dict(reasons.most_common())}")


def _write_overlays(plan, args, db_path: Path, out_dir: Path, stamp: str) -> None:
    from memory.maintenance.topology_backfill.apply import HIGH, MEDIUM, apply_plan

    confidences = (HIGH, MEDIUM) if args.include_medium else (HIGH,)
    report = apply_plan(
        plan,
        confidences=confidences,
        dry_run=not args.apply,
        backup_dir=out_dir / f"topology_overlay_backup_{stamp}",
        source={"kind": "android_room", "db": str(db_path), "plan_at": plan.generated_at},
    )
    mode = "[写入]" if args.apply else "[预演]"
    for item in report.results:
        print(
            f"{mode} {item.conversation_id}: 节点 {item.nodes} / 事件 {item.events} "
            f"/ 置信度不足跳过 {item.skipped_low_confidence} -> {item.path}"
        )
    print(f"{mode} 合计 {report.totals()}")
    if not args.apply:
        print("[提示] 加 --apply 才会写覆盖文件；原始事件在任何模式下都不改写")


def main() -> int:
    parser = argparse.ArgumentParser(description="Room 消息树拓扑回填预览")
    parser.add_argument("--db", required=True, help="adb 拉下来的 aveline_database")
    parser.add_argument("--data-root", default="", help="companion_data 根目录")
    parser.add_argument("--session-prefix", default="web_role_", help="只处理该前缀会话")
    parser.add_argument("--session", action="append", default=[], help="只处理指定会话")
    parser.add_argument("--out-dir", default="", help="报告输出目录")
    parser.add_argument("--max-samples", type=int, default=5, help="每类抽样条数")
    parser.add_argument("--no-decisions", action="store_true", help="不写逐事件决策文件")
    parser.add_argument("--apply", action="store_true", help="写入旁挂拓扑覆盖文件")
    parser.add_argument(
        "--include-medium", action="store_true", help="同时收中置信度（模糊）配对"
    )
    args = parser.parse_args()

    started = time.time()
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[错误] 找不到 Room 库: {db_path}")
        return 1
    data_root = Path(args.data_root) if args.data_root else Path(get_companion_data_dir())

    sessions = load_room_sessions(db_path, session_prefix=args.session_prefix)
    requested = [str(item).strip() for item in args.session if str(item).strip()]
    if requested:
        wanted = set(requested)
        sessions = {
            key: value for key, value in sessions.items() if key in wanted
        }
    if not sessions:
        print(f"[空] {db_path} 下没有匹配 {args.session_prefix!r} 的会话")
        return 1

    events, scopes = _load_server_events(data_root, set(sessions))
    if not events:
        print(f"[空] {data_root} 下没有找到这些会话的服务端事件")
        return 1

    plan = build_plan(sessions, events, scopes)
    print(f"[预览] {plan.generated_at}  db={db_path}")
    _print_table(plan)

    stamp = get_current_time().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) if args.out_dir else Path("output") / "evaluation"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"topology_backfill_preview_{stamp}.json"
    payload = {
        "db": str(db_path),
        "data_root": str(data_root),
        **plan.report(max_samples=max(0, args.max_samples)),
    }
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[报告] {report_path}")

    if not args.no_decisions:
        decisions_path = out_dir / f"topology_backfill_decisions_{stamp}.jsonl"
        with open(decisions_path, "w", encoding="utf-8") as handle:
            handle.writelines(
                json.dumps(decision.to_dict(), ensure_ascii=False) + "\n"
                for decision in plan.iter_decisions()
            )
        print(f"[决策] {decisions_path}")

    _write_overlays(plan, args, db_path, out_dir, stamp)
    print(f"[耗时] {round(time.time() - started, 2)}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
