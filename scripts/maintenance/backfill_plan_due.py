"""给已有 plan 梗概回填到期日 ``valid_to``（不调模型），并统计按到期日算出的状态。

    venv_cpu/bin/python scripts/maintenance/backfill_plan_due.py --scope aveline            # 预览
    venv_cpu/bin/python scripts/maintenance/backfill_plan_due.py --scope aveline --apply    # 写入

- 只改当前梗概库（v2 时为 ``notes_v2``），旧库只读不动；不改正文与 ``note_id``，不用重算向量；
- 写入前把当前库整目录备份到 ``output/backups/``；已有 ``valid_to`` 的不动，可重复运行；
- 终端只打印计数（含 open / expired / done / cancelled 分布），不打印梗概正文。
到期日规则见 ``memory/notes/plan_due.py``；过期在读时算，本脚本不写 status。
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from memory.notes import NoteStore
from memory.notes.plan_due import due_timestamp, plan_state


def _patch(note: dict) -> dict | None:
    if note.get("kind") != "plan" or note.get("valid_to"):
        return None
    due = due_timestamp(str(note.get("text") or ""), note.get("occurred_from"))
    return {"valid_to": due} if due else None


def run(scope: str, *, apply: bool, root: Path | None = None, now: float | None = None) -> dict:
    store = NoteStore(scope, root=root)
    now = time.time() if now is None else now
    counts: Counter = Counter()
    targets: list[str] = []
    for cid in store.list_conversations():
        hit = False
        for note in store.list_notes(cid):
            if note.get("kind") != "plan":
                continue
            counts["plans"] += 1
            fields = _patch(note) or {}
            hit = hit or bool(fields)
            counts["would_fill"] += bool(fields)
            counts["has_due"] += bool(note.get("valid_to") or fields)
            counts["state_" + (plan_state({**note, **fields}, now) or "open")] += 1
        if hit:
            targets.append(cid)
    report = dict(counts)
    if not apply or not targets:
        return report
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = ROOT_DIR / "output" / "backups" / f"{store.directory().name}_{scope}_due_{stamp}"
    shutil.copytree(store.directory(), backup)
    report["backup"] = str(backup)
    report["filled"] = sum(store.patch_notes(cid, _patch) for cid in targets)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scope", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--root", default="", help="只改这个目录下的梗概（试验副本用）")
    args = parser.parse_args()
    report = run(args.scope, apply=args.apply, root=Path(args.root) if args.root else None)
    print(f"[{args.scope}] {report}")
    if not args.apply:
        print("（预览模式，未写入；加 --apply 执行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
