"""角色作息 / 当日计划（``character_daily``）合并策略的单元测试。

回归点：2026-10-16 白天在 Linux 跟角色聊了一整天（角色 07:04 就醒了），切到
Windows 后程序刚启动就发了「下午好。这下真睡多了，都四点才起」——Windows 侧的
``sleep_states.json`` 还停在 ``phase=sleeping``，而它是 15:59 重写的（mtime 比
Linux 的 15:13 还新），按 mtime 裁决会把「还在睡」那一份选走。
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sync.learning_data.chat_merge import union_bytes  # noqa: E402
from scripts.sync.learning_data.items import (  # noqa: E402
    BASE_COMPANION,
    MERGE_LIFE_STATE,
    items_for,
)
from scripts.sync.learning_data.life_state_merge import union_life_state  # noqa: E402
from scripts.sync.learning_data.manifest import scan  # noqa: E402

_SLEEP_REL = "character_daily/sleep_states.json"
_DAILY_REL = "character_daily/daily_state.json"

# 2026-10-16 07:04（计划起床）与 15:13（Linux 侧最后写入）
_WAKE_TS = 1792105440.0
_LINUX_LAST_TS = 1792137578.0


def _b(payload, *, crlf: bool = False) -> bytes:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if crlf:
        text = text.replace("\n", "\r\n")
    return text.encode("utf-8")


def _parse(raw: bytes) -> dict:
    return json.loads(raw.decode("utf-8"))


def _sleep(role: str, phase: str, last_ts: float, date: str = "2026-10-16") -> dict:
    return {
        "role_id": role,
        "date": date,
        "phase": phase,
        "planned_wake_time": "07:04",
        "actual_wakeup_ts": _WAKE_TS,
        "last_wake_ts": last_ts,
        "recent_events": [{"event_type": "wakeup", "ts": last_ts}],
    }


def test_awake_side_wins_even_though_sleeping_side_has_newer_mtime():
    """刚开机那端把旧状态重写成更新的 mtime，也不能赢过「已经醒了」的那份。"""
    linux = _b({"aveline": _sleep("aveline", "fully_awake", _LINUX_LAST_TS)})
    windows = _b({"aveline": _sleep("aveline", "sleeping", _WAKE_TS)})

    for left, right in ((windows, linux), (linux, windows)):
        merged = _parse(union_life_state(left, right))
        assert merged["aveline"]["phase"] == "fully_awake"
        assert merged["aveline"]["last_wake_ts"] == _LINUX_LAST_TS


def test_merges_per_role_so_each_side_keeps_its_progress():
    """同一个文件里不同角色可能分别在两端推进，整文件二选一会回退另一端。"""
    left = _b(
        {
            "aveline": _sleep("aveline", "fully_awake", _LINUX_LAST_TS),
            "ling": _sleep("ling", "sleeping", _WAKE_TS),
        }
    )
    right = _b(
        {
            "aveline": _sleep("aveline", "sleeping", _WAKE_TS),
            "ling": _sleep("ling", "fully_awake", _LINUX_LAST_TS + 600),
        }
    )

    merged = _parse(union_life_state(left, right))

    assert merged["aveline"]["phase"] == "fully_awake"
    assert merged["ling"]["phase"] == "fully_awake"
    assert merged["ling"]["last_wake_ts"] == _LINUX_LAST_TS + 600


def test_only_one_side_has_role_keeps_it():
    left = _b({"aveline": _sleep("aveline", "fully_awake", _LINUX_LAST_TS)})
    right = _b({"ling": _sleep("ling", "fully_awake", _LINUX_LAST_TS)})

    merged = _parse(union_life_state(left, right))

    assert set(merged) == {"aveline", "ling"}


def test_is_order_independent_and_idempotent():
    a = _b({"aveline": _sleep("aveline", "fully_awake", _LINUX_LAST_TS)})
    b = _b({"ling": _sleep("ling", "fully_awake", _LINUX_LAST_TS + 60)})
    c = _b({"aveline": _sleep("aveline", "sleeping", _WAKE_TS)})

    first = union_life_state(union_life_state(a, b), c)
    second = union_life_state(union_life_state(c, b), a)

    assert first == second
    assert union_life_state(first, first) == first


def test_crlf_input_is_normalised_to_lf():
    """Windows 写出来的是 CRLF、Linux 是 LF，不统一会让两端指纹永远不一致。"""
    linux = _b({"aveline": _sleep("aveline", "fully_awake", _LINUX_LAST_TS)})
    windows = _b({"aveline": _sleep("aveline", "sleeping", _WAKE_TS)}, crlf=True)

    merged = union_life_state(linux, windows)

    assert b"\r\n" not in merged
    assert merged.endswith(b"\n")


def test_nested_role_map_in_daily_state():
    """daily_state.json 的角色表在 plans 下面，逐角色合并后其余键取更新的一侧。"""
    linux = _b(
        {
            "date": "2026-10-16",
            "plans": {
                "aveline": {"role_id": "aveline", "date": "2026-10-16", "generated_at": _LINUX_LAST_TS},
                "ling": {"role_id": "ling", "date": "2026-10-16", "generated_at": _WAKE_TS},
            },
        }
    )
    windows = _b(
        {
            "date": "2026-10-16",
            "plans": {
                "aveline": {"role_id": "aveline", "date": "2026-10-16", "generated_at": _WAKE_TS},
                "ling": {"role_id": "ling", "date": "2026-10-16", "generated_at": _LINUX_LAST_TS + 30},
            },
        }
    )

    merged = _parse(union_life_state(linux, windows))

    assert merged["date"] == "2026-10-16"
    assert merged["plans"]["aveline"]["generated_at"] == _LINUX_LAST_TS
    assert merged["plans"]["ling"]["generated_at"] == _LINUX_LAST_TS + 30


def test_unparsable_side_returns_none():
    """解析不了就交回冲突流程，不硬判。"""
    good = _b({"aveline": _sleep("aveline", "fully_awake", _LINUX_LAST_TS)})

    assert union_life_state(b"{ not json", good) is None
    assert union_life_state(b'["array"]', good) is None


def test_union_bytes_dispatches_life_state():
    linux = _b({"aveline": _sleep("aveline", "fully_awake", _LINUX_LAST_TS)})
    windows = _b({"aveline": _sleep("aveline", "sleeping", _WAKE_TS)})

    merged = _parse(union_bytes(MERGE_LIFE_STATE, windows, linux))

    assert merged["aveline"]["phase"] == "fully_awake"


def test_scan_marks_character_daily_as_life_state(tmp_path):
    local = tmp_path / "repo"
    (local / "character_daily").mkdir(parents=True)
    for name in ("sleep_states.json", "daily_state.json", "activity_instances.json"):
        (local / "character_daily" / name).write_text("{}", encoding="utf-8")

    modes = {}
    found = scan(items_for(["life_state"]), {BASE_COMPANION: local}.get, modes=modes)

    sleep_key = f"{BASE_COMPANION}:{_SLEEP_REL}"
    assert sleep_key in found
    assert modes[sleep_key] == MERGE_LIFE_STATE
    assert modes[f"{BASE_COMPANION}:{_DAILY_REL}"] == MERGE_LIFE_STATE
    # 未纳入清单的文件不该被 life_state 分组捎带进来
    assert f"{BASE_COMPANION}:character_daily/activity_instances.json" not in found
