"""验证 Room 拓扑回填（第一档覆盖层 + 第二档推断）在本机真实数据上的效果。

只读：读取已写入的覆盖文件与原始事件，不改任何数据。需要本机 companion_data
与手机库备份（默认 companion_data/backups/aveline_room_20261026/）：

    venv_cpu/bin/python tests/scripts/memory/verify_topology_backfill_live.py [--db 路径]

检查三件事：
1. 覆盖层叠加后每棵树无父子冲突、待定节点极少；
2. 模拟 Android 请求（边界 = 激活路径最后 100 个节点）走生产读闸门：
   旁支泄漏 = 0、主线误隐藏 = 0；
3. 推断规则在手机窗口内对照真实树：准确率 ≥ 90%（召回只报告不设门槛）；
4. 没有请求路径的读（nightly / 主动消息 / QQ 侧检索走持久化游标）：游标的父链连到
   真根，隐藏条数与第 2 步模拟请求相当（2026-10-26 回复主动消息后游标跳到孤立根，
   无请求读隐藏数从约 1000 涨到 7170）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.services.chat_history_store import get_chat_history_store  # noqa: E402
from memory.maintenance.topology_backfill import load_room_sessions  # noqa: E402
from memory.topology.cursors import cursor_for  # noqa: E402
from memory.topology.inferred import superseded_event_ids  # noqa: E402
from memory.topology.overlay import load_overlay, scope_of  # noqa: E402
from memory.topology.read_gate import filter_raw_events  # noqa: E402
from memory.topology.tree_registry import get_tree_registry  # noqa: E402

DEFAULT_DB = ROOT_DIR / "companion_data" / "backups" / "aveline_room_20261026" / "aveline_database"
MIN_PRECISION = 0.90
# 手机库是某个时刻的导出，之后的新对话（含被重新生成替换掉的回复）会让两种读略有出入
HIDDEN_DRIFT_ABS = 50
HIDDEN_DRIFT_RATIO = 0.05


def _check(cid, session, store) -> dict:
    events = store.list_conversation_events(cid, limit=0)
    overlay = load_overlay(cid, scope_of(events, cid))
    if not overlay:
        return {"cid": cid, "ok": False, "error": "没有覆盖文件（先跑 backfill_topology_from_room.py --apply）"}
    tree = get_tree_registry().tree(cid)
    on_path = set(session.active_path)
    scope = {"allowed_message_ids": set(session.active_path[-100:]), "not_after_ts": None, "conversation_id": cid}
    requested = filter_raw_events(events, conversation_id=cid, branch_scope=scope)
    visible = {item.get("event_id") for item in requested.events}
    unrequested = filter_raw_events(events, conversation_id=cid, branch_scope={})
    cursor = cursor_for(cid)
    cursor_grounded = cursor in tree.nodes and tree.is_grounded(cursor)
    drift = abs(unrequested.hidden - requested.hidden)
    drift_ok = drift <= max(HIDDEN_DRIFT_ABS, HIDDEN_DRIFT_RATIO * requested.hidden)
    mapped = overlay["events"]
    leaked = sum(1 for eid in visible if eid in mapped and mapped[eid] not in on_path)
    wrongly_hidden = sum(
        1 for item in events
        if item.get("event_id") not in visible and mapped.get(item.get("event_id")) in on_path
    )
    window = [item for item in events if item.get("timestamp", 0) >= session.window_start and item.get("event_id") in mapped]
    truth = {item["event_id"] for item in window if mapped[item["event_id"]] not in on_path and item.get("role") != "user"}
    predicted = superseded_event_ids(window)
    hit = len(predicted & truth)
    return {
        "cid": cid,
        "conflicts": len(tree.conflicts),
        "pending": len(tree.pending),
        "leaked": leaked,
        "wrongly_hidden": wrongly_hidden,
        "predicted": len(predicted),
        "hit": hit,
        "truth": len(truth),
        "cursor_grounded": cursor_grounded,
        "hidden_request": requested.hidden,
        "hidden_no_request": unrequested.hidden,
        "ok": not tree.conflicts and leaked == 0 and wrongly_hidden == 0 and cursor_grounded and drift_ok,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args()
    if not Path(args.db).exists():
        print(f"[跳过] 找不到手机库备份: {args.db}")
        return 1
    sessions = load_room_sessions(Path(args.db))
    store = get_chat_history_store()
    rows = [_check(cid, session, store) for cid, session in sorted(sessions.items())]
    predicted = sum(row.get("predicted", 0) for row in rows)
    hit = sum(row.get("hit", 0) for row in rows)
    truth = sum(row.get("truth", 0) for row in rows)
    for row in rows:
        if "error" in row:
            print(f"[FAIL] {row['cid']}: {row['error']}")
            continue
        print(
            f"[{'OK' if row['ok'] else 'FAIL'}] {row['cid']}: 冲突 {row['conflicts']} 待定 {row['pending']} "
            f"旁支泄漏 {row['leaked']} 主线误隐藏 {row['wrongly_hidden']} "
            f"游标连根 {'是' if row['cursor_grounded'] else '否'} "
            f"隐藏 请求 {row['hidden_request']} / 无请求 {row['hidden_no_request']}"
        )
    precision = hit / predicted if predicted else 0.0
    recall = hit / truth if truth else 0.0
    precision_ok = precision >= MIN_PRECISION
    print(f"[{'OK' if precision_ok else 'FAIL'}] 推断去重 准确率 {precision:.1%}（门槛 {MIN_PRECISION:.0%}） 召回 {recall:.1%}")
    passed = all(row["ok"] for row in rows) and precision_ok
    print(f"\n结果：{'通过' if passed else '未通过'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
