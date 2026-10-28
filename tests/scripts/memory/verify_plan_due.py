"""验证计划到期日与读时过期（只读，不调模型、不写盘）。

    venv_cpu/bin/python tests/scripts/memory/verify_plan_due.py --scope aveline

对比「只看模型标的 status」和「按到期日算 plan_state」两种口径下，还开着的计划有多少；
同时报到期日覆盖率，以及主对话注入现在会挑出几条计划。只打印计数，不打印正文。
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from memory.notes import NoteStore
from memory.notes.injection.selection import pick_plans
from memory.notes.plan_due import due_timestamp, plan_state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scope", required=True)
    args = parser.parse_args()
    now = time.time()
    store = NoteStore(args.scope)
    plans = [
        n for cid in store.list_conversations() for n in store.list_notes(cid) if n["kind"] == "plan"
    ]
    # 没回填过的按回填后的样子算，回填前后结论一致
    filled = [
        {**n, "valid_to": n.get("valid_to") or due_timestamp(n["text"], n.get("occurred_from"))}
        for n in plans
    ]
    by_model = Counter(n.get("status") or "open" for n in plans)
    by_state = Counter(plan_state(n, now) for n in filled)
    stored_due = sum(1 for n in plans if n.get("valid_to"))
    with_due = sum(1 for n in filled if n.get("valid_to"))
    print(f"[{args.scope}] 计划 {len(plans)} 条")
    print(f"  只看模型 status：{dict(by_model)}")
    print(f"  按到期日算：    {dict(by_state)}")
    print(f"  到期日：已存 {stored_due} 条，可算出 {with_due} 条")
    print(f"  主对话注入候选：{len(pick_plans(filled, now))} 条")
    ok = by_state.get("open", 0) < by_model.get("open", 0) or not plans
    print("通过" if ok else "未通过：过期规则没有减少开着的计划")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
