"""背单词进度与每日生词日志并集合并的单元测试。"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sync.learning_data.chat_merge import union_bytes  # noqa: E402
from scripts.sync.learning_data.items import (  # noqa: E402
    BASE_PROJECT,
    MERGE_DATED_STATE,
    MERGE_VOCAB,
    MERGE_WORD_LIST,
    items_for,
)
from scripts.sync.learning_data.manifest import scan  # noqa: E402
from scripts.sync.learning_data.vocab_merge import (  # noqa: E402
    union_vocab_progress,
    union_word_list,
)

_PROGRESS_REL = "output/user_data/vocab_progress.json"
_DAILY_REL = "data/study_data/English/Words/daily/2026/10/24.txt"
_STATE_REL = "data/study_data/English/Words/daily/_review_queue_state.json"


def _json_bytes(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _load(raw: bytes):
    return json.loads(raw.decode("utf-8"))


def test_progress_union_keeps_words_from_both_sides():
    left = _json_bytes({"alpha": {"reps": 2, "history": [{"timestamp": 100, "quality": 3}]}})
    right = _json_bytes({"beta": {"reps": 1, "history": [{"timestamp": 200, "quality": 4}]}})

    merged = _load(union_vocab_progress(left, right))

    assert set(merged) == {"alpha", "beta"}
    assert merged["alpha"]["reps"] == 2
    assert merged["beta"]["reps"] == 1


def test_progress_union_prefers_latest_review_schedule():
    left = _json_bytes(
        {
            "alpha": {
                "reps": 3,
                "interval": 5,
                "fsrs_last_review": 100,
                "history": [{"timestamp": 100, "quality": 2}],
            }
        }
    )
    right = _json_bytes(
        {
            "alpha": {
                "reps": 7,
                "interval": 20,
                "fsrs_last_review": 200,
                "history": [{"timestamp": 200, "quality": 4}],
            }
        }
    )

    merged = _load(union_vocab_progress(left, right))
    reversed_merged = _load(union_vocab_progress(right, left))

    assert merged == reversed_merged
    assert merged["alpha"]["reps"] == 7
    assert merged["alpha"]["interval"] == 20


def test_progress_union_merges_and_dedupes_history():
    shared = {"timestamp": 100, "quality": 3, "source": "manual_review"}
    left = _json_bytes({"alpha": {"reps": 2, "history": [shared]}})
    right = _json_bytes(
        {
            "alpha": {
                "reps": 3,
                "history": [{"timestamp": 300, "quality": 4}, dict(shared)],
            }
        }
    )

    merged = _load(union_vocab_progress(left, right))

    assert [item["timestamp"] for item in merged["alpha"]["history"]] == [100, 300]


def test_progress_union_is_order_independent_and_idempotent():
    a = _json_bytes({"alpha": {"reps": 1, "history": [{"timestamp": 10, "quality": 1}]}})
    b = _json_bytes({"beta": {"reps": 2, "history": [{"timestamp": 20, "quality": 2}]}})
    c = _json_bytes({"gamma": {"reps": 3, "history": [{"timestamp": 30, "quality": 3}]}})

    first = union_vocab_progress(union_vocab_progress(a, b), c)
    second = union_vocab_progress(union_vocab_progress(c, b), a)

    assert first == second
    assert union_vocab_progress(first, first) == first


def test_progress_union_skips_write_when_either_side_is_malformed():
    """损坏的一侧不能被「能读的一侧」覆盖，交给冲突流程保留原文件。"""
    valid = _json_bytes({"alpha": {"reps": 1}})

    assert union_vocab_progress(b"{not json", valid) is None
    assert union_vocab_progress(valid, b"{not json") is None
    assert union_vocab_progress(b"{not json", b"also broken") is None


def test_progress_union_does_not_treat_due_date_as_recency():
    """到期日越远不代表刚复习过，同词新旧只能按 fsrs_last_review 判。"""
    reviewed_later = _json_bytes(
        {"alpha": {"reps": 5, "fsrs_last_review": 300, "next_review": 200}}
    )
    due_far_future = _json_bytes(
        {"alpha": {"reps": 1, "fsrs_last_review": 100, "next_review": 9_999_999_999}}
    )

    merged = _load(union_vocab_progress(reviewed_later, due_far_future))

    assert merged["alpha"]["reps"] == 5
    assert merged["alpha"]["fsrs_last_review"] == 300


def test_progress_union_history_duplicate_choice_is_order_independent():
    """同一复习事件夹带不同附加字段时，保留哪条与输入顺序无关。"""
    base = {"timestamp": 100, "quality": 3}
    left = _json_bytes({"alpha": {"reps": 2, "history": [dict(base, note="a")]}})
    right = _json_bytes({"alpha": {"reps": 2, "history": [dict(base, note="b")]}})

    assert union_vocab_progress(left, right) == union_vocab_progress(right, left)


def test_word_list_union_keeps_both_sides_and_takes_larger_count():
    left = b"raid 1\namplify\n"
    right = b"raid 3\nbarn 2\n"

    merged = union_word_list(left, right)

    assert merged.decode("utf-8").splitlines() == ["amplify", "barn 2", "raid 3"]
    assert union_word_list(merged, merged) == merged
    assert union_word_list(right, left) == merged


def test_word_list_union_does_not_let_empty_placeholder_win():
    """Windows 侧的 0 字节日志不能覆盖 Linux 侧当天的实际生词。"""
    empty = b""
    content = b"raid 1\namplify 2\n"
    expected = b"amplify 2\nraid 1\n"

    assert union_word_list(empty, content) == expected
    assert union_word_list(content, empty) == expected
    assert union_word_list(b"", b"") == b""


def test_word_list_union_rejects_invalid_utf8():
    """非法 UTF-8 不能用替换字符改写单词键，直接跳过本次合并。"""
    assert union_word_list(b"\xff\xfe", b"raid 1\n") is None
    assert union_word_list(b"raid 1\n", b"\xff\xfe") is None


def test_union_bytes_dispatches_vocab_strategies():
    progress = _json_bytes({"alpha": {"reps": 1}})
    word_list = b"raid 1\n"

    merged_progress = union_bytes(MERGE_VOCAB, progress, b"")
    merged_words = union_bytes(MERGE_WORD_LIST, word_list, b"")

    assert _load(merged_progress) == {"alpha": {"reps": 1}}
    assert merged_words == word_list


def test_scan_assigns_vocab_merge_modes(tmp_path):
    root = tmp_path / "repo"
    for rel in (_PROGRESS_REL, _DAILY_REL, _STATE_REL):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    modes = {}
    found = scan(items_for(["vocab"]), {BASE_PROJECT: root}.get, modes=modes)

    assert f"{BASE_PROJECT}:{_PROGRESS_REL}" in found
    assert modes[f"{BASE_PROJECT}:{_PROGRESS_REL}"] == MERGE_VOCAB
    assert modes[f"{BASE_PROJECT}:{_DAILY_REL}"] == MERGE_WORD_LIST
    assert modes[f"{BASE_PROJECT}:{_STATE_REL}"] == MERGE_DATED_STATE
