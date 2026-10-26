"""聊天事件的幂等写入守护（v3 D4）。

``event_id`` 是 append 时生成的随机 UUID，重投必然产生新 ID，不能当幂等键。
真正可复算的键由 ``memory/topology/events.build_idempotency_key`` 生成，
本模块只负责「同一个文件内同键只写一次」：

- 首次接触某个 JSONL 时按行建立 ``key → event_id`` 快照；
- 之后同键重投直接返回已存在的 event_id，不再追加第二行；
- 老事件没有 ``idempotency_key`` 时不参与去重（不能拿正文猜，避免误伤重复内容）；
- 缓存按文件 LRU，最多保留 ``max_files`` 个；文件被删除时调用方应 ``forget``。

只在本进程内保证；跨进程重投仍会重复写入，这是 append-only JSONL 的已知边界，
由索引层的 ``ensure_sync`` 与审计报告的重复项负责暴露。
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Tuple


class IdempotencyGuard:
    def __init__(self, *, max_files: int = 8) -> None:
        self._max_files = max(1, int(max_files))
        self._cache: "OrderedDict[str, Dict[str, str]]" = OrderedDict()
        self._lock = threading.RLock()

    def reserve(
        self,
        file_path: Path,
        payloads: Sequence[Mapping[str, object]],
    ) -> Tuple[List[Dict[str, object]], Dict[int, str]]:
        """返回 (需要写入的 payload, {入参下标: 已存在的 event_id})。"""
        accepted: List[Dict[str, object]] = []
        duplicates: Dict[int, str] = {}
        with self._lock:
            keys = self._keys_for(file_path)
            for index, payload in enumerate(payloads):
                key = str(payload.get("idempotency_key") or "").strip()
                if not key:
                    accepted.append(dict(payload))
                    continue
                existing = keys.get(key)
                if existing is not None:
                    duplicates[index] = existing
                    continue
                keys[key] = str(payload.get("event_id") or "")
                accepted.append(dict(payload))
        return accepted, duplicates

    def forget(self, file_path: Path) -> None:
        with self._lock:
            self._cache.pop(self._cache_key(file_path), None)

    # ---- 内部 -----------------------------------------------------------
    @staticmethod
    def _cache_key(file_path: Path) -> str:
        try:
            return str(Path(file_path).resolve())
        except OSError:
            return str(file_path)

    def _keys_for(self, file_path: Path) -> Dict[str, str]:
        cache_key = self._cache_key(file_path)
        keys = self._cache.get(cache_key)
        if keys is not None:
            self._cache.move_to_end(cache_key)
            return keys
        keys = self._load_keys(file_path)
        self._cache[cache_key] = keys
        while len(self._cache) > self._max_files:
            self._cache.popitem(last=False)
        return keys

    @staticmethod
    def _load_keys(file_path: Path) -> Dict[str, str]:
        keys: Dict[str, str] = {}
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw)
                    except Exception:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    key = str(payload.get("idempotency_key") or "").strip()
                    if key:
                        keys[key] = str(payload.get("event_id") or "")
        except OSError:
            return keys
        return keys


_GUARD = IdempotencyGuard()


def get_idempotency_guard() -> IdempotencyGuard:
    return _GUARD
