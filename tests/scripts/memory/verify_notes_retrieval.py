"""验证派生笔记检索（v3 G）：真实 bge-small-zh 向量 + 临时笔记库，不碰真实数据。

    venv_cpu/bin/python tests/scripts/memory/verify_notes_retrieval.py

检查：① 问句与梗概不共享词时（「住在哪个城市」vs「在重庆长大」）混合检索仍能命中，
纯 BM25 命中不了；② 来源事件被闸门隐藏的梗概不返回；③ 向量旁挂缓存第二次查询不再现算；
④ 输出带对话时间与来源事件。
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from memory.notes import NoteStore, embeddings, paths
from memory.notes.retrieval import NoteRetriever

CID = "web_role_aveline"
NOTES = [
    ("s1", "Master说他从小在重庆长大，之后也一直待在这边，没去别的地方工作。", ["e1", "e2"]),
    ("s2", "Master今天中午吃了牛肉汤和葱油饼，吃撑了。", ["e3"]),
    ("s3", "Master说他把早上的抹茶拿铁换成了乌龙茶，觉得抹茶腻。", ["e4"]),
    ("s4", "Master在兄弟分支里说自己搬去了杭州。", ["e5"]),
]


def main() -> int:
    checks = []
    with tempfile.TemporaryDirectory() as tmp:
        paths.notes_dir = lambda scope: Path(tmp) / scope  # type: ignore[assignment]
        store = NoteStore("aveline")
        for index, (sid, text, events) in enumerate(NOTES):
            store.replace_segment(
                CID,
                sid,
                "segment-episode-2",
                [{"kind": "episode", "text": text, "source_event_ids": tuple(events)}],
                segment_source_event_ids=events,
                occurred_from=1_790_000_000.0 + index * 3600,
            )
        real = embeddings.default_embedder()
        calls = []

        def counting(texts):
            calls.append(len(texts))
            return real(texts)

        def gate(payloads, _cid, _scope):
            return {"e5"}  # s4 的来源在兄弟线上

        retriever = NoteRetriever("aveline", store=store, embedder=counting, gate=gate)
        started = time.time()
        hits = retriever.search("我住在哪个城市", conversation_id=CID, limit=2)
        first_ms = (time.time() - started) * 1000
        checks.append(("语义命中：住哪 → 重庆长大", bool(hits) and "重庆" in hits[0]["text"]))
        checks.append(("兄弟线梗概（杭州）不返回", all("杭州" not in h["text"] for h in hits)))
        bm25_only = retriever.search("我住在哪个城市", conversation_id=CID, use_vectors=False)
        checks.append(("纯 BM25 命中不了（证明需要混合检索）", not bm25_only))
        checks.append(
            ("输出带时间与来源", hits and hits[0]["occurred_from"] and hits[0]["source_event_ids"])
        )
        before = sum(calls)
        started = time.time()
        retriever.search("我现在喝什么茶", conversation_id=CID, limit=1)
        second_ms = (time.time() - started) * 1000
        checks.append(("第二次查询只算问句向量（命中旁挂缓存）", sum(calls) - before == 1))
        print(f"首次查询 {first_ms:.0f}ms（含笔记向量现算），第二次 {second_ms:.0f}ms")
    for label, ok in checks:
        print(f"[{'OK' if ok else 'FAIL'}] {label}")
    return 0 if all(ok for _label, ok in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
