"""验证按段提取的输入管线（v3 F3 · WP1）。

默认：临时目录里造一份聊天记录端到端跑一遍（游标目录、覆盖层都指到临时目录，不碰真实数据）：

    venv_cpu/bin/python tests/scripts/memory/verify_segment_inputs.py

``--live``：对本机真实聊天记录只读跑一遍，**只打印计数**（段数、封口数、每段轮数分布、
拓扑状态分布），不输出任何正文。会话列表优先走派生 SQLite 索引，索引落后时会被补齐，
这与生产读路径的行为一致，不改原始 JSONL：

    venv_cpu/bin/python tests/scripts/memory/verify_segment_inputs.py --live --scope aveline
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.services.chat_history_store import ChatHistoryStore
from memory.nightly.config import DEFAULT_NIGHTLY_CONFIG
from memory.nightly.segment_jobs.inputs import (
    SegmentParams,
    collect_segment_inputs,
    summarize_inputs,
)

CONV = "verify_segment_inputs__scope__aveline"
BASE_TS = 1_700_000_000.0


def _isolate(tmp: Path) -> None:
    """游标与覆盖层指到临时目录，避免往真实 companion_data 写游标。"""
    from memory.topology import cursors, tree_registry

    cursors.base_dir_for = lambda scope: tmp / "cursors" / scope
    cursors.load_overlay = lambda _cid, _scope: None
    tree_registry._default_overlay_loader = lambda _cid, _scope: None
    cursors.reset_cursor_cache()
    tree_registry.reset_tree_registry()


def _write(store: ChatHistoryStore, role: str, content: str, offset: float, **extra) -> dict:
    metadata = dict(extra.pop("metadata", {}) or {})
    return store.append_events(
        [
            {
                "conversation_id": CONV,
                "role": role,
                "content": content,
                "message_id": extra.pop("message_id"),
                "event_type": extra.pop("event_type", "message"),
                "metadata": metadata,
                "now_dt": datetime.fromtimestamp(BASE_TS + offset, tz=timezone.utc),
                **extra,
            }
        ]
    )[0]


def run_temp() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _isolate(tmp)
        store = ChatHistoryStore(tmp / "chat_history")
        ids: dict = {}
        # 第 1 段：无节点历史，同一句提交两次（第一轮回复被重新生成取代），带一条思考
        ids["u1"] = _write(store, "user", "周末去哪", 0, message_id="m1")["event_id"]
        ids["a1_old"] = _write(store, "assistant", "旧回复", 1, message_id="m1")["event_id"]
        ids["u1_dup"] = _write(store, "user", "周末去哪", 20, message_id="m2")["event_id"]
        ids["thought"] = _write(
            store, "assistant", "思考", 20.5, message_id="m2", event_type="chat_thought"
        )["event_id"]
        ids["a1"] = _write(store, "assistant", "新回复", 21, message_id="m2")["event_id"]
        # 空闲 1 小时后第 2 段，再过 1 小时第 3 段（尾段，按 now 判断是否封口）
        ids["u2"] = _write(store, "user", "第二段", 3600, message_id="m3")["event_id"]
        ids["a2"] = _write(store, "assistant", "回答二", 3601, message_id="m3")["event_id"]
        ids["u3"] = _write(store, "user", "第三段", 7200, message_id="m4")["event_id"]
        ids["a3"] = _write(store, "assistant", "回答三", 7201, message_id="m4")["event_id"]

        def reader(cid: str):
            return store.list_conversation_events(cid, limit=0)

        params = SegmentParams.from_config(DEFAULT_NIGHTLY_CONFIG)
        kwargs = {"params": params, "conversations": [CONV], "store": store, "tree_reader": reader}
        early = collect_segment_inputs("aveline", now=BASE_TS + 7300, **kwargs)
        late = collect_segment_inputs("aveline", now=BASE_TS + 7201 + 1801, **kwargs)
        again = collect_segment_inputs("aveline", now=BASE_TS + 7201 + 1801, **kwargs)

        first = late[0] if late else None
        checks = {
            "未封口尾段不产出": len(early) == 2 and len(late) == 3,
            "旧回复被去掉": bool(first) and ids["a1_old"] not in first.segment.source_event_ids,
            "思考不进段": all(ids["thought"] not in item.segment.source_event_ids for item in late),
            "重复提交合并": bool(first)
            and first.segment.source_event_ids == [ids["u1"], ids["a1"]]
            and first.aliases == ((ids["u1_dup"], ids["u1"]),),
            "重复计算 ID 不变": [i.segment_id for i in late] == [i.segment_id for i in again],
        }
        print(
            json.dumps(
                {"summary": summarize_inputs(late), "checks": checks}, ensure_ascii=False, indent=2
            )
        )
        return 0 if all(checks.values()) else 1


def run_live(scopes: list) -> int:
    params = SegmentParams.from_config(DEFAULT_NIGHTLY_CONFIG)
    report = {}
    for scope in scopes:
        items = collect_segment_inputs(scope, params=params, include_open=True)
        report[scope] = summarize_inputs(items)
    print(json.dumps({"params": params.__dict__, "scopes": report}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="对本机真实数据只读、只打印计数")
    parser.add_argument("--scope", action="append", default=None, help="--live 时的 scope，可重复")
    args = parser.parse_args()
    if args.live:
        return run_live(args.scope or ["aveline"])
    return run_temp()


if __name__ == "__main__":
    sys.exit(main())
