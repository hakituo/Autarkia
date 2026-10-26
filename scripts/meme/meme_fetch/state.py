"""增量状态：已入库文件的内容哈希索引，保证重复运行只补新文件。"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.utils.logger import get_logger

logger = get_logger("meme_fetch_state")

STATE_FILENAME = ".state.json"
STATE_VERSION = 1


@dataclass
class FetchState:
    """_inbox/.state.json 的内存形态。"""

    path: Path
    hashes: dict[str, str] = field(default_factory=dict)
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    dirty: bool = False

    @classmethod
    async def load(cls, inbox_root: Path) -> FetchState:
        """读取状态文件；不存在或损坏时返回空状态（不阻断抓取）。"""
        path = inbox_root / STATE_FILENAME
        state = cls(path=path)
        if not path.is_file():
            return state

        def _read() -> dict[str, Any]:
            return json.loads(path.read_text(encoding="utf-8"))

        try:
            raw = await asyncio.to_thread(_read)
        except Exception as exc:  # noqa: BLE001 - 状态坏了按空处理，最多多做一次去重
            logger.warning(f"状态文件读取失败，按空状态继续: {path}: {exc}")
            return state
        if not isinstance(raw, dict):
            return state
        hashes = raw.get("hashes")
        if isinstance(hashes, dict):
            state.hashes = {str(k): str(v) for k, v in hashes.items()}
        sources = raw.get("sources")
        if isinstance(sources, dict):
            state.sources = {str(k): v for k, v in sources.items() if isinstance(v, dict)}
        return state

    def known(self, digest: str) -> bool:
        """该内容是否已经入过库。"""
        return digest in self.hashes

    def record(self, digest: str, rel_path: str) -> None:
        """登记一次成功入库。"""
        if digest not in self.hashes:
            self.hashes[digest] = rel_path
            self.dirty = True

    def record_source(self, source_id: str, summary: dict[str, Any]) -> None:
        """记录某个源本次运行的统计。"""
        self.sources[source_id] = summary
        self.dirty = True

    async def save(self) -> None:
        """原子写回状态文件（内容无变化时跳过）。"""
        if not self.dirty:
            return
        payload = {
            "version": STATE_VERSION,
            "hashes": dict(sorted(self.hashes.items())),
            "sources": self.sources,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)

        def _write() -> None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, self.path)

        try:
            await asyncio.to_thread(_write)
        except OSError as exc:
            logger.warning(f"状态文件写入失败: {self.path}: {exc}")
            return
        self.dirty = False
