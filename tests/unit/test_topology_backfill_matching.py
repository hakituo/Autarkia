"""Room → 服务端事件拓扑回填的轮级配对单测。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple

from memory.maintenance.topology_backfill import build_plan, load_room_sessions

CID = "web_role_test"
BASE_MS = 1_800_000_000_000
BASE_S = BASE_MS // 1000


def _write_db(path: Path, rows: List[Tuple[Any, ...]]) -> Path:
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
    return path


def _node(
    node_id: str,
    parent: str | None,
    text: str,
    offset_ms: int,
    *,
    user: bool,
    variant: int = 0,
    active: bool = True,
    message_type: str = "text",
) -> Tuple[Any, ...]:
    return (
        node_id,
        CID,
        parent,
        text,
        BASE_MS + offset_ms,
        1 if user else 0,
        variant,
        1 if active else 0,
        message_type,
    )


def _event(
    event_id: str,
    message_id: str,
    role: str,
    event_type: str,
    content: str,
    offset_s: int,
) -> Dict[str, Any]:
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


def _plan(tmp_path: Path, rows: List[Tuple[Any, ...]], events: List[Dict[str, Any]]):
    db_path = _write_db(tmp_path / "aveline_database", rows)
    sessions = load_room_sessions(db_path)
    return build_plan(
        sessions,
        {CID: events},
        {CID: ["test_scope"]},
    )


def _decisions(plan) -> Dict[str, Any]:
    result = {}
    for decision in plan.iter_decisions():
        result[decision.event_id] = decision
    return result


def test_exact_turn_and_thought(tmp_path: Path) -> None:
    rows = [
        _node("u1", None, "你好", 0, user=True),
        _node("a1", "u1", "在呢", 1000, user=False),
    ]
    events = [
        _event("e1", "m1", "user", "chat_message", "你好", 0),
        _event("e2", "m1", "assistant", "chat_reply", "在呢。", 1),
        _event("e3", "m1", "system", "chat_thought", "想了", 1),
    ]
    plan = _plan(tmp_path, rows, events)
    decisions = _decisions(plan)

    assert decisions["e1"].client_node_id == "u1"
    assert decisions["e1"].match_method == "user_exact"
    assert decisions["e1"].is_root is True
    assert decisions["e2"].client_node_id == "a1"
    assert decisions["e2"].match_method == "assistant_exact"
    assert decisions["e3"].client_node_id == "a1"
    assert decisions["e3"].match_method == "thought_attached"
    assert plan.sessions[CID].counts()["coverage_in_window"] == 1.0


def test_regeneration_reuses_user_node_and_marks_duplicate(tmp_path: Path) -> None:
    rows = [
        _node("u1", None, "你好", 0, user=True),
        _node("a1", "u1", "版本一", 1000, user=False, variant=0, active=False),
        _node("a2", "u1", "版本二", 2000, user=False, variant=1),
    ]
    events = [
        _event("e1", "m1", "user", "chat_message", "你好", 0),
        _event("e2", "m1", "assistant", "chat_reply", "版本一。", 1),
        _event("e3", "m2", "user", "chat_message", "你好", 10),
        _event("e4", "m2", "assistant", "chat_reply", "版本二。", 11),
    ]
    plan = _plan(tmp_path, rows, events)
    decisions = _decisions(plan)

    assert decisions["e1"].client_node_id == "u1"
    assert decisions["e3"].client_node_id == "u1"
    assert decisions["e3"].duplicate_submission is True
    assert decisions["e2"].client_node_id == "a1"
    assert decisions["e4"].client_node_id == "a2"
    assert plan.sessions[CID].counts()["duplicate_submissions"] == 1


def test_media_user_message_with_empty_caption(tmp_path: Path) -> None:
    rows = [
        _node("u1", None, "", 0, user=True, message_type="image"),
        _node("a1", "u1", "看到了", 1000, user=False),
    ]
    events = [
        _event(
            "e1",
            "m1",
            "user",
            "chat_message",
            "[图片: /output/image/upload_1.jpg]",
            0,
        ),
        _event("e2", "m1", "assistant", "chat_reply", "看到了", 1),
    ]
    plan = _plan(tmp_path, rows, events)
    decisions = _decisions(plan)

    assert decisions["e1"].client_node_id == "u1"
    assert decisions["e1"].match_method in {"user_media", "user_media_time"}
    assert decisions["e2"].client_node_id == "a1"


def test_wrapper_uses_latest_message(tmp_path: Path) -> None:
    rows = [_node("u1", None, "最新一句", 0, user=True)]
    events = [
        _event(
            "e1",
            "m1",
            "user",
            "chat_message",
            "【你之前没回的消息】\n1. 旧的\n\n【用户最新消息】\n最新一句",
            0,
        )
    ]
    plan = _plan(tmp_path, rows, events)
    decision = _decisions(plan)["e1"]

    assert decision.client_node_id == "u1"
    assert decision.match_method == "user_wrapper"


def test_fuzzy_assistant_match(tmp_path: Path) -> None:
    rows = [
        _node("u1", None, "你好", 0, user=True),
        _node(
            "a1",
            "u1",
            "今天天气不错我们一起去公园散步吧顺便买点水果回来",
            1000,
            user=False,
        ),
    ]
    events = [
        _event("e1", "m1", "user", "chat_message", "你好", 0),
        _event(
            "e2",
            "m1",
            "assistant",
            "chat_reply",
            "今天天气不错我们一起去公园走走顺便买点水果回来",
            1,
        ),
    ]
    plan = _plan(tmp_path, rows, events)
    decision = _decisions(plan)["e2"]

    assert decision.client_node_id == "a1"
    assert decision.match_method == "assistant_fuzzy"
    assert decision.confidence == "medium"


def test_unmatched_assistant_stays_unknown(tmp_path: Path) -> None:
    rows = [
        _node("u1", None, "你好", 0, user=True),
        _node("a1", "u1", "在呢", 1000, user=False),
    ]
    events = [
        _event("e1", "m1", "user", "chat_message", "你好", 0),
        _event("e2", "m1", "assistant", "chat_reply", "完全是另一段回复内容呢", 1),
    ]
    plan = _plan(tmp_path, rows, events)
    decisions = _decisions(plan)

    assert decisions["e2"].client_node_id == ""
    assert decisions["e2"].reason == "assistant_unmatched"
    assert decisions["e1"].client_node_id == "u1"


def test_parent_without_event_is_not_re_rooted(tmp_path: Path) -> None:
    rows = [
        _node("p0", None, "早安", -1000, user=False),
        _node("u1", "p0", "你好", 0, user=True),
        _node("a1", "u1", "在呢", 1000, user=False),
    ]
    events = [
        _event("e1", "m1", "user", "chat_message", "你好", 0),
        _event("e2", "m1", "assistant", "chat_reply", "在呢", 1),
    ]
    plan = _plan(tmp_path, rows, events)
    decisions = _decisions(plan)

    assert decisions["e1"].client_node_id == "u1"
    assert decisions["e1"].parent_node_id == "p0"
    assert decisions["e1"].is_root is False
    assert decisions["e1"].parent_without_event is True
    counts = plan.sessions[CID].counts()
    assert counts["parent_without_event_nodes"] == 1


def test_proactive_assistant_only_turn(tmp_path: Path) -> None:
    rows = [_node("a0", None, "早安，该起了", 0, user=False)]
    events = [
        _event("e1", "p1", "assistant", "proactive_message", "早安，该起了。", 0)
    ]
    plan = _plan(tmp_path, rows, events)
    decision = _decisions(plan)["e1"]

    assert decision.client_node_id == "a0"
    assert decision.match_method == "assistant_only_exact"
    assert decision.is_root is True


def test_room_integrity_reports_missing_parent_and_active_conflict(
    tmp_path: Path,
) -> None:
    rows = [
        _node("u1", "missing", "你好", 0, user=True),
        _node("a1", "u1", "在呢", 1000, user=False),
        _node("u2", None, "再来", 2000, user=True),
        _node("a2", "u2", "版本一", 3000, user=False, variant=0),
        _node("a3", "u2", "版本二", 4000, user=False, variant=1),
    ]
    db_path = _write_db(tmp_path / "aveline_database", rows)
    session = load_room_sessions(db_path)[CID]

    assert session.integrity["missing_parent"] == 1
    assert session.integrity["bad_active_groups"] >= 1
    assert session.integrity["roots"] == 1
