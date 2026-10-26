"""端到端验证：Room → 服务端事件拓扑回填 preview。

用临时 Room 库 + 临时 companion_data 跑真实 CLI，检查覆盖率、重复提交、
thought 挂载与媒体消息匹配，不依赖本机真实数据。

    venv_cpu/bin/python tests/scripts/memory/verify_topology_backfill.py
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "scripts" / "maintenance" / "backfill_topology_from_room.py"
CID = "web_role_test"
BASE_MS = 1_800_000_000_000
BASE_S = BASE_MS // 1000


def _write_db(path: Path) -> None:
    rows = [
        ("u1", CID, None, "你好", BASE_MS, 1, 0, 1, "text"),
        ("a1", CID, "u1", "版本一", BASE_MS + 1000, 0, 0, 0, "text"),
        ("a2", CID, "u1", "版本二", BASE_MS + 2000, 0, 1, 1, "text"),
        ("u2", CID, "a2", "看这个", BASE_MS + 3000, 1, 0, 1, "image"),
        ("a3", CID, "u2", "看到了", BASE_MS + 4000, 0, 0, 1, "text"),
    ]
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE messages ("
        "id TEXT PRIMARY KEY, sessionId TEXT, parentId TEXT, text TEXT, "
        "timestamp INTEGER, isUser INTEGER, variantIndex INTEGER, "
        "isActiveVariant INTEGER, messageType TEXT)"
    )
    con.executemany("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


def _event(
    event_id: str,
    message_id: str,
    role: str,
    event_type: str,
    content: str,
    offset_s: int,
) -> dict:
    return {
        "event_id": event_id,
        "conversation_id": CID,
        "message_id": message_id,
        "role": role,
        "event_type": event_type,
        "content": content,
        "timestamp": BASE_S + offset_s,
        "storage_scope": "test_scope",
    }


def _write_events(data_root: Path) -> None:
    chat_dir = data_root / "aveline_data" / "chat_history" / "2026" / "10" / "25"
    chat_dir.mkdir(parents=True)
    events = [
        _event("e1", "m1", "user", "chat_message", "你好", 0),
        _event("e2", "m1", "assistant", "chat_reply", "版本一。", 1),
        _event("e3", "m1", "system", "chat_thought", "想", 1),
        _event("e4", "m2", "user", "chat_message", "你好", 10),
        _event("e5", "m2", "assistant", "chat_reply", "版本二。", 11),
        _event(
            "e6",
            "m3",
            "user",
            "chat_message",
            "[图片: /output/image/x.jpg]\n看这个",
            20,
        ),
        _event("e7", "m3", "assistant", "chat_reply", "看到了。", 21),
    ]
    path = chat_dir / f"{CID}.jsonl"
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory(prefix="topology_backfill_verify_") as tmp:
        root = Path(tmp)
        db_path = root / "aveline_database"
        data_root = root / "companion_data"
        out_dir = root / "out"
        _write_db(db_path)
        _write_events(data_root)

        command = [
            sys.executable,
            str(CLI),
            "--db",
            str(db_path),
            "--data-root",
            str(data_root),
            "--out-dir",
            str(out_dir),
        ]
        result = subprocess.run(
            command, capture_output=True, text=True, cwd=str(ROOT), check=False
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            return 1

        report_paths = sorted(out_dir.glob("topology_backfill_preview_*.json"))
        decision_paths = sorted(out_dir.glob("topology_backfill_decisions_*.jsonl"))
        if len(report_paths) != 1 or len(decision_paths) != 1:
            print(f"FAIL 输出文件数量异常: {report_paths} {decision_paths}")
            return 1

        report = json.loads(report_paths[0].read_text(encoding="utf-8"))
        totals = report["totals"]
        session = report["sessions"][CID]
        checks = [
            ("窗口内事件", totals["in_window"], 7),
            ("可配事件", totals["matched_in_window"], 7),
            ("覆盖率", totals["coverage_in_window"], 1.0),
            ("重复提交", totals["duplicate_submissions"], 1),
            ("断父节点", totals["parent_without_event_nodes"], 0),
        ]
        for name, actual, expected in checks:
            if actual != expected:
                failures.append(f"{name}: {actual} != {expected}")

        methods = session["events"]["by_method"]
        if methods.get("assistant_exact") != 3:
            failures.append(f"assistant_exact: {methods.get('assistant_exact')} != 3")
        if methods.get("thought_attached") != 1:
            failures.append(
                f"thought_attached: {methods.get('thought_attached')} != 1"
            )
        if methods.get("user_media") != 1:
            failures.append(f"user_media: {methods.get('user_media')} != 1")

        decisions = [
            json.loads(line)
            for line in decision_paths[0].read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        by_id = {item["event_id"]: item for item in decisions}
        expected_nodes = {
            "e1": "u1",
            "e2": "a1",
            "e3": "a1",
            "e4": "u1",
            "e5": "a2",
            "e6": "u2",
            "e7": "a3",
        }
        for event_id, node_id in expected_nodes.items():
            actual = by_id.get(event_id, {}).get("client_node_id")
            if actual != node_id:
                failures.append(f"{event_id} 节点: {actual} != {node_id}")

    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print("PASS 7/7 事件可配，覆盖率 100%，重复提交 1，断父 0")
    print("PASS thought 挂载、媒体 caption、重新生成变体均正确")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
