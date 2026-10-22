# -*- coding: utf-8 -*-
"""Study Daily 学习域 - 数据变更指纹。

- GET /study-daily/version 返回学习数据的轻量指纹：
  - daily_version:   Study/Daily 下所有 .md 的 (rel_path, mtime_ns, size) 指纹
  - library_version: Study 下学习库笔记的同类指纹（与 /library 共用缓存）

客户端进入学习页或回到前台时先请求本接口做一次比对；指纹没变就跳过
日历/计划/日记/笔记的全量拉取，避免「内容没改也重新加载一遍并闪刷新」。
"""

import asyncio
import hashlib
import threading
import time
from pathlib import Path
from typing import Any, Dict, Tuple

from fastapi import APIRouter

from core.api.contract import error_response, success_response
from core.api.error_response import ErrorCode, get_friendly_error_message
from core.utils import data_paths

from .study_daily_library import get_library_snapshot

router = APIRouter(prefix="/study-daily", tags=["study-daily"])

# 与 library 列表缓存同量级：覆盖客户端一次进入的连续请求
_CACHE_TTL_SECONDS = 5.0
_cache_lock = threading.Lock()
# root -> (expire_at, version)
_daily_cache: Dict[str, Tuple[float, str]] = {}


def _scan_daily_version_sync(root: Path) -> str:
    """扫描 Daily 目录并计算内容指纹（空目录返回固定空摘要）。"""
    if not root.exists() or not root.is_dir():
        return hashlib.sha1(b"").hexdigest()

    files = []
    for md_file in root.rglob("*.md"):
        rel = md_file.relative_to(root)
        # 排除隐藏目录/文件，与笔记接口的可见范围保持一致
        if any(part.startswith(".") for part in rel.parts):
            continue
        if not md_file.is_file():
            continue
        files.append((rel.as_posix(), md_file))
    # rglob 顺序不稳定，先按 rel_path 排序再算指纹
    files.sort(key=lambda item: item[0].lower())

    digest = hashlib.sha1()
    for rel_path, md_file in files:
        try:
            stat = md_file.stat()
        except OSError:
            continue
        digest.update(f"{rel_path}|{stat.st_mtime_ns}|{stat.st_size}\n".encode("utf-8"))
    return digest.hexdigest()


def get_daily_version(root: Path) -> str:
    """获取 Daily 目录指纹（带短 TTL 缓存）。"""
    key = str(root.resolve())
    now = time.monotonic()
    with _cache_lock:
        cached = _daily_cache.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]

    version = _scan_daily_version_sync(root)
    with _cache_lock:
        _daily_cache[key] = (now + _CACHE_TTL_SECONDS, version)
    return version


def clear_daily_version_cache() -> None:
    """清空指纹缓存（测试隔离与目录切换时使用）。"""
    with _cache_lock:
        _daily_cache.clear()


@router.get("/version", summary="获取学习数据变更指纹")
async def get_study_version():
    """返回 Daily 与学习库两部分的内容指纹。

    客户端只需比对这两个字符串：都一致时即可完全跳过全量拉取。
    """
    try:
        daily_root = data_paths.get_study_daily_dir()
        library_root = data_paths.get_study_root_dir()

        # 两个目录互不重叠，并行扫描；library 结果与 /library 端点共用缓存
        daily_task = asyncio.to_thread(get_daily_version, daily_root)
        library_task = asyncio.to_thread(get_library_snapshot, library_root)
        daily_version, library_snapshot = await asyncio.gather(daily_task, library_task)
        library_version = library_snapshot[1]

        payload: Dict[str, Any] = {
            "daily_version": daily_version,
            "library_version": library_version,
        }
        return success_response(data=payload)
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))
