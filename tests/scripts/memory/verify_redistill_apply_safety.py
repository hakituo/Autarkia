"""验证 redistill 回写消歧与人物线索过滤（P0/B1+B2）。

不读写真实记忆池，只用内存假数据跑纯逻辑：
    venv_cpu\\Scripts\\python.exe tests\\scripts\\memory\\verify_redistill_apply_safety.py
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from memory.maintenance.redistill_apply import (  # noqa: E402
    MemoryTargetIndex,
    SourceEvent,
    apply_plan,
    build_apply_plan,
)
from memory.nightly.distillation_codec import DistillationCodec  # noqa: E402


class _Manager:
    def __init__(self, records, fail_on=()):
        self.weighted_memories = records
        self.lock = threading.RLock()
        self._use_rw_lock = False
        self.fail_on = set(fail_on)

    def update_memory_distillation(self, memory_id, summary, keywords, **_kwargs):
        if memory_id in self.fail_on or memory_id not in self.weighted_memories:
            return False
        record = self.weighted_memories[memory_id]
        record["summary"] = summary
        record["keywords"] = list(keywords)
        record["search_keywords"] = list(keywords)
        record["is_distilled"] = True
        return True

    def _mark_keyword_index_dirty_locked(self, _memory_id):
        return None

    def _schedule_save(self):
        return None


def _record(role, message_id, event_id, conversation_id="cid"):
    return {
        "role": role,
        "source": role,
        "summary": "old",
        "keywords": ["old"],
        "search_keywords": ["old"],
        "display_tags": [],
        "is_distilled": True,
        "metadata": {
            "message_id": message_id,
            "event_ref": {
                "event_id": event_id,
                "conversation_id": conversation_id,
                "relative_path": f"2026/10/25/{conversation_id}.jsonl",
            },
        },
    }


def _event(role, message_id, event_id, conversation_id="cid"):
    return SourceEvent(
        event_id=event_id,
        conversation_id=conversation_id,
        role=role,
        message_id=message_id,
        content="正文",
        timestamp=1.0,
    )


def _check_same_turn_split() -> bool:
    records = {"m-u": _record("user", "t1", "e-u"), "m-a": _record("assistant", "t1", "e-a")}
    manager = _Manager(records)
    index = MemoryTargetIndex.from_manager(manager)
    plan = build_apply_plan(
        index,
        [_event("user", "t1", "e-u"), _event("assistant", "t1", "e-a")],
        {1: ("用户梗概", []), 2: ("角色梗概", [])},
    )
    result = apply_plan(manager, plan)
    ok = (
        result["committed"]
        and records["m-u"]["summary"] == "用户梗概"
        and records["m-a"]["summary"] == "角色梗概"
    )
    print(f"[{'OK' if ok else 'FAIL'}] 同轮 user/assistant 各自回写自己的记忆")
    return ok


def _check_ambiguous_blocks() -> bool:
    records = {"m1": _record("assistant", "t2", "e1"), "m2": _record("assistant", "t2", "e2")}
    manager = _Manager(records)
    index = MemoryTargetIndex.from_manager(manager)
    plan = build_apply_plan(
        index,
        [SourceEvent("", "cid", "assistant", "t2", "x", 1.0)],
        {1: ("新梗概", [])},
    )
    result = apply_plan(manager, plan)
    ok = (not result["committed"]) and records["m1"]["summary"] == "old"
    print(f"[{'OK' if ok else 'FAIL'}] 同轮多候选 → 判 ambiguous 且不写入")
    return ok


def _check_rollback() -> bool:
    records = {"m-u": _record("user", "t3", "e-u3"), "m-a": _record("assistant", "t3", "e-a3")}
    manager = _Manager(records, fail_on={"m-a"})
    index = MemoryTargetIndex.from_manager(manager)
    plan = build_apply_plan(
        index,
        [_event("user", "t3", "e-u3"), _event("assistant", "t3", "e-a3")],
        {1: ("用户梗概", []), 2: ("角色梗概", [])},
    )
    result = apply_plan(manager, plan)
    ok = (not result["committed"]) and records["m-u"]["summary"] == "old"
    print(f"[{'OK' if ok else 'FAIL'}] 第二条失败 → 第一条回滚，不留半批")
    return ok


def _check_people_filter() -> bool:
    view = {"role_id": "aveline", "role_name": "Aveline", "user_name": "阿远"}
    names = DistillationCodec.build_excluded_people_names(view)
    kept = DistillationCodec.filter_people_mentions(
        ["Aveline", "Aveline", "阿远", "我", "Ling", "同学Aveline", "小张"],
        names,
    )
    ok = kept == ["Ling", "同学Aveline", "小张"]
    print(f"[{'OK' if ok else 'FAIL'}] 人物线索剔除对话双方、保留互识/第三方/同名第三方 → {kept}")
    return ok


def main() -> int:
    checks = [
        _check_same_turn_split,
        _check_ambiguous_blocks,
        _check_rollback,
        _check_people_filter,
    ]
    results = [check() for check in checks]
    passed = sum(1 for item in results if item)
    print(f"\n结果：{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
