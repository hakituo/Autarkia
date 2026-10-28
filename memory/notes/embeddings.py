"""笔记向量的旁挂缓存：``notes/_vectors/<会话>.npz``（note_id + float16 矩阵）。

一次工具调用里不能现算上万条梗概的向量（bge-small 约 70 条/秒），所以向量在
回填 / 写入后补算并落盘，查询时只算问题本身。缺的向量查询时也会补，但单次有上限，
超出部分本次只走 BM25，下次再补。删除缓存文件即可全部重算。
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from . import paths

Embedder = Callable[[list[str]], Sequence[Sequence[float]]]

#: 单次查询最多现算的笔记向量数，避免冷启动时一次调用卡几十秒
MAX_NEW_PER_CALL = 64
_lock = threading.Lock()


def vectors_path(scope: str, conversation_id: str) -> Path:
    stem = paths.notes_path(scope, conversation_id).stem
    return paths.notes_dir(scope) / "_vectors" / f"{stem}.npz"


def default_embedder() -> Embedder:
    from memory.embedding_generator import get_embedding_generator

    generator = get_embedding_generator()
    return lambda texts: generator.generate_embeddings_batch(list(texts))


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


def _read(path: Path) -> dict[str, np.ndarray]:
    if not path.exists():
        return {}
    try:
        with np.load(path, allow_pickle=False) as data:
            return {
                str(note_id): row.astype(np.float32)
                for note_id, row in zip(data["ids"], data["vectors"])
            }
    except Exception:  # noqa: BLE001 - 缓存坏了就当没有，重算
        return {}


def _write(path: Path, vectors: dict[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = np.array(list(vectors), dtype=str)
    matrix = np.stack(list(vectors.values())).astype(np.float16)
    tmp = path.with_name(path.name + ".tmp.npz")
    np.savez(tmp, ids=ids, vectors=matrix)
    tmp.replace(path)


def _seed_from_legacy(
    scope: str, conversation_id: str, cached: dict[str, np.ndarray], live: dict[str, str]
) -> int:
    """v2 过渡期双读旧梗概时，旧梗概的向量直接从旧目录缓存搬过来，不重算。"""
    legacy = paths.legacy_notes_dir(scope)
    if legacy is None:
        return 0
    wanted = {note_id for note_id in live if note_id not in cached}
    if not wanted:
        return 0
    stem = paths.notes_path(scope, conversation_id).stem
    found = {k: v for k, v in _read(legacy / "_vectors" / f"{stem}.npz").items() if k in wanted}
    cached.update(found)
    return len(found)


def load_vectors(
    scope: str,
    conversation_id: str,
    notes: Sequence[dict[str, Any]],
    embedder: Embedder,
    *,
    max_new: int = MAX_NEW_PER_CALL,
) -> dict[str, np.ndarray]:
    """返回 ``note_id -> 归一化向量``；缺的按上限补算并写回，过期 note 的向量顺手剔除。"""
    return load_vectors_counted(scope, conversation_id, notes, embedder, max_new=max_new)[0]


def load_vectors_counted(
    scope: str,
    conversation_id: str,
    notes: Sequence[dict[str, Any]],
    embedder: Embedder,
    *,
    max_new: int = MAX_NEW_PER_CALL,
) -> tuple[dict[str, np.ndarray], int]:
    """同 ``load_vectors``，另返回本次现算的条数（供调用方在多个会话间共用一份预算）。"""
    path = vectors_path(scope, conversation_id)
    with _lock:
        cached = _read(path)
        live = {str(note["note_id"]): str(note.get("text") or "") for note in notes}
        seeded = _seed_from_legacy(scope, conversation_id, cached, live)
        missing = [note_id for note_id in live if note_id not in cached][: max(max_new, 0)]
        stale = set(cached) - set(live)
        if missing:
            fresh = _normalize(np.asarray(embedder([live[i] for i in missing]), dtype=np.float32))
            cached.update(zip(missing, fresh))
        for note_id in stale:
            cached.pop(note_id, None)
        if (missing or stale or seeded) and cached:
            _write(path, cached)
    vectors = {
        note_id: _normalize(vec[None, :])[0] for note_id, vec in cached.items() if note_id in live
    }
    return vectors, len(missing)


__all__ = [
    "MAX_NEW_PER_CALL",
    "default_embedder",
    "load_vectors",
    "load_vectors_counted",
    "vectors_path",
]
