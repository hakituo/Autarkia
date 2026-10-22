# -*- coding: utf-8 -*-
"""Study Daily 学习日报域 - 学习库笔记（Study 根目录）。

- GET /study-daily/library        列出各科目文件夹下的 .md 笔记
- GET /study-daily/library/note   按相对路径读取单篇

目录结构约定：
- Study/<科目>/xxx.md            → subject=科目名
- Study/<科目>/<子目录>/xxx.md   → subject=科目名（递归收集）
- Study/备忘录.md                → subject="未分类"（根目录散文件）

过滤规则：
- 排除隐藏文件/目录（以 . 开头）
- 排除 _LIBRARY_EXCLUDED_DIRS 指定的顶层目录

列表扫描带短 TTL 进程内缓存：客户端进入学习页会先请求 /study-daily/version
做变更比对，随后才可能拉列表；缓存让这两次请求复用同一份扫描结果，
也避免用户短时间内反复进入时重复全盘 rglob + stat。
"""

import asyncio
import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Query

from core.api.contract import error_response, success_response
from core.api.error_response import ErrorCode, get_friendly_error_message
from core.utils import data_paths

from .study_daily_shared import _read_text_async

router = APIRouter(prefix="/study-daily", tags=["study-daily"])

# 学习库扫描时排除的顶层目录（Daily 由日报域接口覆盖，media 为媒体资源）
_LIBRARY_EXCLUDED_DIRS = {"daily", "media", "study_tools"}

# 缓存 TTL：覆盖「version → library」两次连续请求，同时保证改动能尽快可见
_CACHE_TTL_SECONDS = 5.0
_cache_lock = threading.Lock()
# root -> (expire_at, notes, version)
_library_cache: Dict[str, Tuple[float, List[Dict[str, Any]], str]] = {}


def _is_hidden_path(path: Path) -> bool:
    """判断路径中是否包含隐藏文件/目录（以 . 开头的路径段）。"""
    return any(part.startswith(".") for part in path.parts)


def _stat_or_none(path: Path) -> Optional[os.stat_result]:
    """读取文件 stat；文件在扫描过程中被删除时返回 None。"""
    try:
        return path.stat()
    except OSError:
        return None


def _scan_library_sync(root: Path) -> Tuple[List[Dict[str, Any]], str]:
    """扫描学习根目录，返回 (笔记列表, 内容指纹)。

    指纹由每个文件的 rel_path + mtime_ns + size 拼成，按 rel_path 排序后
    计算 sha1——目录内文件增删改都会让它变化，客户端据此判断是否需要重拉。
    """
    notes: List[Dict[str, Any]] = []
    if not root.exists() or not root.is_dir():
        return notes, hashlib.sha1(b"").hexdigest()

    entries: List[Tuple[str, Path]] = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        # 跳过隐藏目录/文件
        if entry.name.startswith("."):
            continue
        # 根目录散放的 .md 文件归入"未分类"
        if entry.is_file() and entry.name.endswith(".md"):
            entries.append((entry.name, entry))
            continue
        if not entry.is_dir():
            continue
        if entry.name.lower() in _LIBRARY_EXCLUDED_DIRS:
            continue
        for md_file in entry.rglob("*.md"):
            if not md_file.is_file():
                continue
            rel = md_file.relative_to(root)
            if _is_hidden_path(rel):
                continue
            entries.append((rel.as_posix(), md_file))

    # 按 rel_path 排序，保证不同目录同名文件（rglob 顺序不稳定）的指纹稳定
    entries.sort(key=lambda item: item[0].lower())

    digest = hashlib.sha1()
    for _, md_file in entries:
        stat = _stat_or_none(md_file)
        if stat is None:
            continue
        rel_path = md_file.relative_to(root).as_posix()
        parts = rel_path.split("/")
        subject = "未分类" if len(parts) == 1 else parts[0]
        notes.append(
            {
                "subject": subject,
                "filename": md_file.name,
                "rel_path": rel_path,
                # 毫秒整数：客户端按 long 解析，浮点秒会被 kotlinx 判成非整数而丢成 0
                "updated_ts": int(stat.st_mtime * 1000),
            }
        )
        digest.update(f"{rel_path}|{stat.st_mtime_ns}|{stat.st_size}\n".encode("utf-8"))
    return notes, digest.hexdigest()


def get_library_snapshot(root: Path, force: bool = False) -> Tuple[List[Dict[str, Any]], str]:
    """获取学习库列表与版本指纹（带短 TTL 缓存）。

    @param force 跳过缓存，用于客户端手动刷新
    """
    key = str(root.resolve())
    now = time.monotonic()
    with _cache_lock:
        cached = _library_cache.get(key)
        if cached is not None and not force and cached[0] > now:
            return [dict(item) for item in cached[1]], cached[2]

    notes, version = _scan_library_sync(root)
    with _cache_lock:
        _library_cache[key] = (now + _CACHE_TTL_SECONDS, notes, version)
    return [dict(item) for item in notes], version


def clear_library_cache() -> None:
    """清空列表缓存（测试隔离与目录切换时使用）。"""
    with _cache_lock:
        _library_cache.clear()


@router.get("/library", summary="获取学习库笔记列表（study_root 科目文件夹）")
async def list_library_notes(
    force: bool = Query(False, description="跳过短 TTL 缓存（手动刷新）"),
):
    """列出学习根目录下各科目文件夹中的所有 .md 笔记。

    返回 data.notes 数组（含 subject/filename/rel_path/updated_ts）、
    data.total 与 data.version（内容指纹，供客户端做增量判断）。
    """
    try:
        root = data_paths.get_study_root_dir()
        notes, version = await asyncio.to_thread(get_library_snapshot, root, force)
        return success_response(data={"notes": notes, "total": len(notes), "version": version})
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


def _resolve_library_note_path(root: Path, rel_path: str) -> Optional[Path]:
    """将相对路径解析为绝对路径并做安全校验（防路径穿越，仅限 .md）。"""
    rel = (rel_path or "").strip().replace("\\", "/").lstrip("/")
    if not rel or not rel.endswith(".md"):
        return None
    if "\x00" in rel:
        return None
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


@router.get("/library/note", summary="读取学习库笔记内容（按相对路径）")
async def get_library_note(
    path: str = Query(..., description="相对于学习根目录的路径，如 Mathematics/极限.md"),
):
    """读取学习库中指定笔记的完整 Markdown 内容。"""
    try:
        root = data_paths.get_study_root_dir()
        target = _resolve_library_note_path(root, path)
        if target is None:
            return error_response(
                ErrorCode.RESOURCE_NOT_FOUND,
                message=f"学习库笔记不存在或路径无效：{path}",
            )
        content = await _read_text_async(target)
        rel = target.relative_to(root).as_posix()
        stat = _stat_or_none(target)
        return success_response(
            data={
                "filename": target.name,
                "path": rel,
                "content": content,
                # 客户端用它判断本地镜像是否与后端一致，避免旧内容被当成新内容
                "updated_ts": int(stat.st_mtime * 1000) if stat is not None else 0,
            }
        )
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))
