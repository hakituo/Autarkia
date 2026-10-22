# -*- coding: utf-8 -*-
"""Study Daily 学习日报域 - 专题笔记读取。

专题笔记（Daily/YYYY/MM[/DD]/*.md）：
- GET /study-daily/notes
- GET /study-daily/notes/{filename}

学习库笔记（Study/<科目>/**.md）已拆分到 study_daily_library.py，
两者端点语义不同（一个按文件名跨目录取最新，一个按相对路径读取）。
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from core.api.contract import error_response, success_response
from core.api.error_response import ErrorCode, get_friendly_error_message
from core.utils.data_paths import get_study_daily_dir

from .study_daily_shared import (
    _is_progress_filename,
    _is_safe_filename,
    _read_text_async,
)

router = APIRouter(prefix="/study-daily", tags=["study-daily"])


# ==================== 专题笔记 ====================


def _list_topic_notes_sync(base: Path) -> List[Dict[str, Any]]:
    """扫描所有专题笔记。

    专题笔记 = .md 文件且文件名不是 DD.md / diary.md / plan.md。
    支持两种目录结构 (兼容历史和当前实际存放方式):
      1. Daily/YYYY/MM/专题笔记.md          (旧约定, 月目录直接放文件)
      2. Daily/YYYY/MM/DD/专题笔记.md       (实际结构, 笔记放在日子目录内)
    """
    notes: List[Dict[str, Any]] = []
    if not base.exists() or not base.is_dir():
        return notes

    def _collect_md_files(directory: Path, year: str, month: str, day: Optional[str]) -> None:
        """收集 directory 下所有合法专题笔记 .md 文件 (非 progress/diary/plan)"""
        if not directory.is_dir():
            return
        for entry in sorted(directory.iterdir()):
            if not entry.is_file() or not entry.name.endswith(".md"):
                continue
            # 排除进度文件 DD.md / 每日日记 diary.md / 每日计划 plan.md
            if _is_progress_filename(entry.name):
                continue
            if entry.name.lower() in ("diary.md", "plan.md"):
                continue
            # path 字段: 优先带 day, 否则只到 month
            path_suffix = (
                f"{year}/{month}/{day}/{entry.name}" if day else f"{year}/{month}/{entry.name}"
            )
            notes.append(
                {
                    "filename": entry.name,
                    "path": path_suffix,
                    "year": int(year),
                    "month": int(month),
                }
            )

    for year_dir in sorted(base.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        year = year_dir.name
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue
            month = month_dir.name
            # 结构 1: 月目录直接放的 .md (旧约定)
            _collect_md_files(month_dir, year, month, day=None)
            # 结构 2: 月目录下的日子子目录里放的 .md (实际结构)
            for day_dir in sorted(month_dir.iterdir()):
                if not day_dir.is_dir() or not day_dir.name.isdigit():
                    continue
                _collect_md_files(day_dir, year, month, day=day_dir.name)
    return notes


@router.get("/notes", summary="获取所有专题笔记列表")
async def list_notes():
    """获取所有专题笔记列表（文件名和路径）"""
    try:
        base = get_study_daily_dir()
        notes = await asyncio.to_thread(_list_topic_notes_sync, base)
        return success_response(data={"notes": notes, "total": len(notes)})
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


def _find_note_sync(base: Path, filename: str) -> Optional[Path]:
    """按文件名查找专题笔记，返回最近修改的一份（跨年月/日子目录可能重名）

    支持两种目录结构 (与 _list_topic_notes_sync 一致):
      1. Daily/YYYY/MM/filename           (旧约定)
      2. Daily/YYYY/MM/DD/filename        (实际结构)
    """
    if not base.exists() or not base.is_dir():
        return None
    candidates: List[Path] = []
    for year_dir in base.iterdir():
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for month_dir in year_dir.iterdir():
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue
            # 结构 1: 月目录直接查
            candidate = month_dir / filename
            if candidate.is_file():
                candidates.append(candidate)
            # 结构 2: 进入日子目录查
            for day_dir in month_dir.iterdir():
                if not day_dir.is_dir() or not day_dir.name.isdigit():
                    continue
                candidate_in_day = day_dir / filename
                if candidate_in_day.is_file():
                    candidates.append(candidate_in_day)
    if not candidates:
        return None
    # 按修改时间倒序，取最新一份
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


@router.get("/notes/{filename}", summary="读取指定专题笔记内容")
async def get_note(filename: str):
    """读取指定专题笔记内容（按文件名查找，返回最近修改的一份）"""
    if not _is_safe_filename(filename):
        return error_response(
            ErrorCode.INVALID_PARAMETER,
            message=f"文件名无效：{filename}",
        )
    try:
        base = get_study_daily_dir()
        target = await asyncio.to_thread(_find_note_sync, base, filename)
        if target is None:
            return error_response(
                ErrorCode.RESOURCE_NOT_FOUND,
                message=f"专题笔记不存在：{filename}",
            )
        content = await _read_text_async(target)
        rel_path = str(target.relative_to(base)).replace("\\", "/")
        return success_response(
            data={
                "filename": filename,
                "path": rel_path,
                "content": content,
            }
        )
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))
