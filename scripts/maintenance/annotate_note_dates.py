"""给已有梗概的相对时间补具体日期（不调模型）：「明天」→「明天（9月26日）」。

    venv_cpu/bin/python scripts/maintenance/annotate_note_dates.py --scope aveline            # 预览
    venv_cpu/bin/python scripts/maintenance/annotate_note_dates.py --scope aveline --apply    # 写入

- 只改当前梗概库（v2 时为 ``notes_v2``），旧库只读不动；``note_id`` 不变；
- 写入前把当前库整目录备份到 ``output/backups/``；改过的梗概重算向量缓存（本地 bge）；
- 已补过（``text_revisions`` 含 ``dates-v1``）的不再补，可重复运行；终端只打印计数。
推算规则见 ``memory/notes/dates.py``。
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from memory.notes import NoteStore, embeddings
from memory.notes.dates import annotate

MARK = "dates-v1"


def _rewrite(note: dict) -> str | None:
    if MARK in (note.get("text_revisions") or []):
        return None
    text = annotate(str(note.get("text") or ""), note.get("occurred_from"))
    return text if text != note.get("text") else None


def _refresh_vectors(store: NoteStore, conversation_id: str, changed_ids: set[str]) -> None:
    path = embeddings.vectors_path(store.scope, conversation_id)
    cached = embeddings._read(path)
    for note_id in changed_ids:
        cached.pop(note_id, None)
    if cached:
        embeddings._write(path, cached)
    elif path.exists():
        path.unlink()
    notes = store.list_notes(conversation_id)
    embeddings.load_vectors(store.scope, conversation_id, notes, embeddings.default_embedder(), max_new=10**9)


def run(scope: str, *, apply: bool, root: Path | None = None) -> dict:
    store = NoteStore(scope, root=root)
    counts = {"notes": 0, "would_change": 0, "changed": 0}
    plans: dict[str, set[str]] = {}
    for cid in store.list_conversations():
        for note in store.list_notes(cid):
            counts["notes"] += 1
            if _rewrite(note) is not None:
                counts["would_change"] += 1
                plans.setdefault(cid, set()).add(str(note["note_id"]))
    if not apply or not plans:
        return counts
    backup = ROOT_DIR / "output" / "backups" / f"{store.directory().name}_{scope}_{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copytree(store.directory(), backup)
    counts["backup"] = str(backup)
    for cid, ids in plans.items():
        counts["changed"] += store.rewrite_texts(cid, _rewrite, mark=MARK)
        if root is None:
            _refresh_vectors(store, cid, ids)
    return counts


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
