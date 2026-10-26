# -*- coding: utf-8 -*-
"""价目表快照的落盘与读取：抓取结果只经由这里进出磁盘。

与 ``sync.py`` 的分工：本模块只管「一份目录怎么存、怎么读、新不新鲜」，
什么时候该重抓、抓回来怎么合并都在 ``sync.py``。
调用方一律显式传路径（``snapshot_path(cfg)``），这样测试只要替换调用方的
``snapshot_path`` 就能把整条链路指向临时目录。
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from core.llm.token_stats.pricing.models import PriceCatalog
from core.llm.token_stats.pricing.settings import snapshot_path
from core.utils.time.time_utils import get_current_time

#: 内存里已解析的快照与其文件指纹
_CACHE: Dict[str, Any] = {"signature": None, "catalog": None}


def now_iso_local() -> str:
    """按项目时区返回 ISO 时间串（走 time_utils，不用裸 datetime.now）。"""
    return get_current_time().isoformat()


def parse_iso(value: Any) -> Optional[datetime]:
    """解析快照里的时间串；没带时区按 UTC 处理。"""
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def read_snapshot(path: Optional[Path] = None) -> Tuple[PriceCatalog, Optional[float]]:
    """读本地快照，返回 (目录, 文件修改时间戳)；文件不存在返回空目录与 None。"""
    target = path or snapshot_path()
    try:
        mtime = target.stat().st_mtime
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return PriceCatalog(), None
    if not isinstance(raw, dict):
        return PriceCatalog(), None
    return PriceCatalog.from_dict(raw.get("catalog") or raw), mtime


def write_snapshot(catalog: PriceCatalog, path: Optional[Path] = None) -> Path:
    """原子写快照：先写临时文件再替换，避免半截 JSON 被并发读到。"""
    target = path or snapshot_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"catalog": catalog.to_dict(), "written_at": now_iso_local()}
    fd, tmp = tempfile.mkstemp(prefix=".pricing-", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    reset_cache()
    return target


def load_catalog(path: Optional[Path] = None) -> PriceCatalog:
    """带内存缓存地读取快照；文件没变不重复解析。"""
    target = path or snapshot_path()
    try:
        signature: Any = target.stat().st_mtime_ns
    except OSError:
        signature = None
    if _CACHE["signature"] == signature and _CACHE["catalog"] is not None:
        return _CACHE["catalog"]
    catalog, _ = read_snapshot(target)
    _CACHE["signature"] = signature
    _CACHE["catalog"] = catalog
    return catalog


def reset_cache() -> None:
    """清空内存缓存（测试与手动同步后用）。"""
    _CACHE["signature"] = None
    _CACHE["catalog"] = None


def age_seconds(catalog: PriceCatalog) -> Optional[float]:
    """快照距今多少秒；没有同步时间返回 None（视为从没抓过）。"""
    moment = parse_iso(catalog.synced_at)
    if moment is None:
        return None
    return max(0.0, (get_current_time() - moment).total_seconds())
