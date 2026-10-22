"""按天派生状态文件（_review*_state.json）合并策略的单元测试。

回归点：2026-10-16 实测，Linux 用停在 10-03 的进度生成了 365 条复习队列
（mtime 00:45），Windows 用 10-15 的进度生成了 32 条（mtime 00:17）；
按 mtime 裁决会把用旧数据生成的那份选走。
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sync.learning_data.chat_merge import union_bytes  # noqa: E402
from scripts.sync.learning_data.dated_state_merge import union_dated_state  # noqa: E402
from scripts.sync.learning_data.items import (  # noqa: E402
    BASE_PROJECT,
    MERGE_DATED_STATE,
    SyncItem,
    items_for,
)
from scripts.sync.learning_data.manifest import scan  # noqa: E402

_REL_DIR = "data/study_data/English/Words/daily"
_QUEUE_REL = f"{_REL_DIR}/_review_queue_state.json"


def _b(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _queue(source_date: str, count: int, selected_at: str) -> dict:
    return {
        "version": 5,
        "review_date": "2026/10/16",
        "batch_size": 0,
        "entries": [
            {"word": f"w{i}", "review_source": "daily_backlog", "source_date": source_date}
            for i in range(count)
        ],
        "selected_at": selected_at,
    }


def test_fresher_source_date_wins_over_newer_mtime():
    """用旧进度生成的那份即使文件更新（mtime 更晚），也必须输给用新进度生成的。"""
    stale = _b(_queue("2026/10/03", 365, "2026-10-16 00:45:03"))
    fresh = _b(_queue("2026/10/15", 32, "2026-10-16 00:17:21"))

    assert union_dated_state(stale, fresh) == fresh
    assert union_dated_state(fresh, stale) == fresh


def test_selected_at_breaks_tie_on_same_source_date():
    older = _b(_queue("2026/10/15", 32, "2026-10-16 00:17:21"))
    newer = _b(_queue("2026/10/15", 40, "2026-10-16 00:45:03"))

    assert union_dated_state(older, newer) == newer
    assert union_dated_state(newer, older) == newer


def test_is_order_independent_and_idempotent():
    a = _b(_queue("2026/10/03", 5, "2026-10-16 00:45:03"))
    b = _b(_queue("2026/10/15", 3, "2026-10-16 00:17:21"))
    c = _b(_queue("2026/10/10", 9, "2026-10-16 00:30:00"))

    first = union_dated_state(union_dated_state(a, b), c)
    second = union_dated_state(union_dated_state(c, b), a)
    assert first == second
    assert union_dated_state(first, first) == first


def test_top_level_source_date_takes_priority():
    """_review_source_state.json 的 source_date 在顶层。"""
    stale = _b({"review_date": "2026/10/16", "source_date": "2026/10/03", "selected_at": "2026-10-16 00:53:24"})
    fresh = _b({"review_date": "2026/10/16", "source_date": "2026/10/15", "selected_at": "2026-10-16 00:53:24"})

    assert union_dated_state(stale, fresh) == fresh


def test_unparsable_side_returns_none():
    """解析不了就交回冲突流程，不硬判。"""
    assert union_dated_state(b"{ not json", _b(_queue("2026/10/15", 1, "x"))) is None
    assert union_dated_state(b'["array"]', _b(_queue("2026/10/15", 1, "x"))) is None


def test_union_bytes_dispatches_dated_state():
    stale = _b(_queue("2026/10/03", 3, "2026-10-16 00:45:03"))
    fresh = _b(_queue("2026/10/15", 1, "2026-10-16 00:17:21"))

    assert union_bytes(MERGE_DATED_STATE, stale, fresh) == fresh


def test_scan_marks_review_state_as_dated_state(tmp_path):
    """递归项在前、_review*_state.json 项在后，扫描时后者要覆盖合并策略。"""
    local = tmp_path / "repo"
    daily = local / _REL_DIR
    daily.mkdir(parents=True)
    for name in (
        "_review_queue_state.json",
        "_review_batch_state.json",
        "_review_source_state.json",
        "2026-10-15.txt",
    ):
        (daily / name).write_text("{}", encoding="utf-8")

    modes = {}
    found = scan(items_for(["vocab"]), {BASE_PROJECT: local}.get, modes=modes)

    queue_key = f"{BASE_PROJECT}:{_QUEUE_REL}"
    other_key = f"{BASE_PROJECT}:{_REL_DIR}/2026-10-15.txt"

    assert queue_key in found
    assert modes[queue_key] == MERGE_DATED_STATE
    assert modes[f"{BASE_PROJECT}:{_REL_DIR}/_review_batch_state.json"] == MERGE_DATED_STATE
    assert modes[other_key] != MERGE_DATED_STATE  # 每日生词文件仍是整文件复制
