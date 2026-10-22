"""学习库笔记列表与变更指纹接口回归测试。

背景（2026-10-17）：
    安卓端每次进入「学习 → 更多 → 笔记」都要等后端全盘 rglob + stat，
    明明笔记没改也会重新拉一遍；库大时首屏要等几秒。
    后端新增 /study-daily/version 指纹与 /library 的短 TTL 缓存，
    客户端据此先展示本地快照、无变化则跳过全量拉取。

本文件固化：
- 列表接口返回稳定的内容指纹；
- 文件增删改会让指纹变化；
- 隐藏目录/排除目录不参与扫描；
- 缓存命中时不重复扫描，force=True 可绕过；
- 笔记相对路径的路径穿越会被拒绝。
"""

import asyncio
import os
from pathlib import Path

import pytest

from routers.v1 import study_daily_library as library
from routers.v1 import study_daily_version as version


@pytest.fixture(autouse=True)
def _clear_cache():
    library.clear_library_cache()
    version.clear_daily_version_cache()
    yield
    library.clear_library_cache()
    version.clear_daily_version_cache()


def _write(root: Path, rel: str, content: str = "# note\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _touch(path: Path, ts: float) -> None:
    os.utime(path, (ts, ts))


def test_library_snapshot_contains_notes_and_version(tmp_path):
    _write(tmp_path, "Physics/动量.md")
    _write(tmp_path, "Physics/章节/能量.md")
    _write(tmp_path, "备忘录.md")

    notes, fingerprint = library.get_library_snapshot(tmp_path, force=True)

    assert len(notes) == 3
    assert fingerprint
    by_path = {n["rel_path"]: n for n in notes}
    assert by_path["Physics/动量.md"]["subject"] == "Physics"
    assert by_path["备忘录.md"]["subject"] == "未分类"
    # 毫秒整数：客户端按 long 解析，浮点秒会被判成非整数而丢成 0
    assert isinstance(by_path["Physics/动量.md"]["updated_ts"], int)


def test_library_version_changes_when_content_changes(tmp_path):
    note = _write(tmp_path, "Physics/动量.md", "# 动量 v1\n")
    _, v1 = library.get_library_snapshot(tmp_path, force=True)

    note.write_text("# 动量 v2\n", encoding="utf-8")
    _touch(note, 1_700_000_100)

    _, v2 = library.get_library_snapshot(tmp_path, force=True)

    assert v1 != v2


def test_library_version_is_stable_for_unchanged_files(tmp_path):
    _write(tmp_path, "Physics/动量.md")

    _, v1 = library.get_library_snapshot(tmp_path, force=True)
    _, v2 = library.get_library_snapshot(tmp_path, force=True)

    assert v1 == v2


def test_library_skips_hidden_and_excluded_dirs(tmp_path):
    _write(tmp_path, "Physics/动量.md")
    _write(tmp_path, ".obsidian/hidden.md")
    _write(tmp_path, "media/shot.md")
    _write(tmp_path, "study_tools/tool.md")
    _write(tmp_path, "Daily/日报.md")

    notes, _ = library.get_library_snapshot(tmp_path, force=True)

    assert [n["rel_path"] for n in notes] == ["Physics/动量.md"]


def test_library_cache_is_reused_until_force(tmp_path):
    _write(tmp_path, "Physics/动量.md")
    notes1, v1 = library.get_library_snapshot(tmp_path)

    _write(tmp_path, "Physics/新增.md")
    # TTL 内：不重新扫描，仍返回旧快照（客户端靠 version 判断要不要 force）
    notes2, v2 = library.get_library_snapshot(tmp_path)

    assert len(notes2) == len(notes1)
    assert v2 == v1

    notes3, v3 = library.get_library_snapshot(tmp_path, force=True)
    assert len(notes3) == 2
    assert v3 != v1


def test_library_note_path_traversal_is_rejected(tmp_path):
    _write(tmp_path, "secret.md", "secret")
    inside = _write(tmp_path, "Physics/动量.md")

    assert library._resolve_library_note_path(tmp_path, "../secret.md") is None
    assert library._resolve_library_note_path(tmp_path, str(inside)) is None
    assert library._resolve_library_note_path(tmp_path, "Physics/动量.md") == inside.resolve()


def test_daily_version_tracks_daily_files(tmp_path):
    daily = tmp_path / "Daily"
    diary = _write(daily, "2026/10/17/diary.md", "v1")

    v1 = version._scan_daily_version_sync(daily)
    diary.write_text("v2", encoding="utf-8")
    _touch(diary, 1_700_000_200)
    v2 = version._scan_daily_version_sync(daily)

    assert v1 != v2


def test_version_endpoint_returns_both_fingerprints(tmp_path, monkeypatch):
    study_root = tmp_path / "Study"
    _write(study_root, "Physics/动量.md")
    daily_root = study_root / "Daily"
    _write(daily_root, "2026/10/17/diary.md", "today")

    monkeypatch.setattr(library.data_paths, "get_study_root_dir", lambda: study_root)
    monkeypatch.setattr(version.data_paths, "get_study_daily_dir", lambda: daily_root)

    payload = asyncio.run(version.get_study_version())

    assert payload["status"] == "success"
    assert payload["data"]["daily_version"]
    assert payload["data"]["library_version"]
