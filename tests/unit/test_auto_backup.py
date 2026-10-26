"""自动备份脚本的单元测试（排除规则 / 增量刷新 / 保留策略 / 端到端）。"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backup import auto_backup, snapshot  # noqa: E402

#: 固定时间注入，避免依赖当前时钟（目录月份可预期）
NOW = datetime(2026, 7, 15, 10, 0, 0)


def _write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _make_repo(root: Path) -> None:
    """构造一棵覆盖各类排除项与白名单的迷你仓库。"""
    _write(root / "companion_data" / "aveline_data" / "chat_history" / "a.jsonl", "hi")
    _write(root / "companion_data" / "aveline_data" / "indexes" / "chat.db", "db")
    _write(root / "companion_data" / "user_data" / "backups" / "backup_1.zip", "zip")
    _write(root / "companion_data" / "temp" / "pending.json", "{}")
    _write(root / "companion_data" / "user_data" / "MEMORY.md", "m")
    _write(root / "companion_data" / "user_data" / "lock.lock", "")
    _write(root / "output" / "user_data" / "vocab_progress.json", "{}")
    _write(root / "output" / "cache" / "blob.bin", "c")
    _write(root / "data" / "study_data" / "word.txt", "w")
    _write(root / "data" / "chromadb_store" / "vector.bin", "v")
    _write(root / ".env", "SECRET=1")
    _write(root / ".env.example", "SECRET=")
    _write(root / "config" / "qweather_private_key.pem", "pem")
    _write(
        root / "core" / "character" / "configs" / "extra" / "2026" / "09" / "distilled_profile.md",
        "d",
    )


def test_iter_tree_files_excludes_derived_and_temp(tmp_path):
    _make_repo(tmp_path)
    names = {
        p.relative_to(tmp_path / "companion_data").as_posix()
        for p in snapshot.iter_tree_files(tmp_path / "companion_data")
    }
    assert "aveline_data/chat_history/a.jsonl" in names
    assert "user_data/MEMORY.md" in names
    assert all("indexes" not in name for name in names)
    assert all("backups" not in name for name in names)
    assert all("temp" not in name for name in names)
    assert all(not name.endswith(".lock") for name in names)


def test_dry_run_writes_nothing(tmp_path):
    repo = tmp_path / "repo"
    _make_repo(repo)
    dest = tmp_path / "backup"
    stats = auto_backup.run_backup(dest=dest, repo_root=repo, apply=False, now=NOW)
    assert stats.copied > 0
    assert not dest.exists()


def test_apply_copies_expected_and_excludes(tmp_path):
    repo = tmp_path / "repo"
    _make_repo(repo)
    dest = tmp_path / "backup"
    stats = auto_backup.run_backup(dest=dest, repo_root=repo, apply=True, now=NOW)
    snap = dest / "2026-07"

    assert not stats.failures
    assert (snap / "companion_data" / "aveline_data" / "chat_history" / "a.jsonl").is_file()
    assert (snap / "output" / "user_data" / "vocab_progress.json").is_file()
    assert (snap / "data" / "study_data" / "word.txt").is_file()
    assert not (snap / "companion_data" / "aveline_data" / "indexes").exists()
    assert not (snap / "companion_data" / "user_data" / "backups").exists()
    assert not (snap / "companion_data" / "temp").exists()
    assert not (snap / "output" / "cache").exists()
    assert not (snap / "data" / "chromadb_store").exists()
    assert not (snap / "companion_data" / "user_data" / "lock.lock").exists()


def test_second_run_skips_unchanged(tmp_path):
    repo = tmp_path / "repo"
    _make_repo(repo)
    dest = tmp_path / "backup"
    first = auto_backup.run_backup(dest=dest, repo_root=repo, apply=True, now=NOW)
    second = auto_backup.run_backup(dest=dest, repo_root=repo, apply=True, now=NOW)
    assert first.skipped == 0
    assert second.copied == 0
    assert second.skipped == first.copied


def test_changed_file_is_recopied(tmp_path):
    repo = tmp_path / "repo"
    _make_repo(repo)
    dest = tmp_path / "backup"
    auto_backup.run_backup(dest=dest, repo_root=repo, apply=True, now=NOW)

    target = repo / "companion_data" / "user_data" / "MEMORY.md"
    target.write_text("changed content", encoding="utf-8")
    second = auto_backup.run_backup(dest=dest, repo_root=repo, apply=True, now=NOW)

    assert second.copied == 1
    copied = dest / "2026-07" / "companion_data" / "user_data" / "MEMORY.md"
    assert copied.read_text(encoding="utf-8") == "changed content"


def test_prune_keeps_recent_snapshots(tmp_path):
    dest = tmp_path / "backup"
    for name in ("2026-01", "2026-02", "2026-03", "2026-04", "manual-dir"):
        (dest / name).mkdir(parents=True)

    planned = snapshot.prune_snapshots(dest, keep=2, apply=False)
    assert planned == ["2026-01", "2026-02"]
    assert (dest / "2026-01").is_dir()  # dry-run 不删

    removed = snapshot.prune_snapshots(dest, keep=2, apply=True)
    assert removed == ["2026-01", "2026-02"]
    assert not (dest / "2026-01").exists()
    assert (dest / "2026-03").is_dir()
    assert (dest / "manual-dir").is_dir()  # 非 YYYY-MM 目录不碰
    assert snapshot.prune_snapshots(dest, keep=0, apply=True) == []


def test_backup_files_whitelist(tmp_path):
    repo = tmp_path / "repo"
    _make_repo(repo)
    dest = tmp_path / "backup"
    auto_backup.run_backup(dest=dest, repo_root=repo, apply=True, now=NOW)
    files = dest / "2026-07" / "files"

    assert (files / ".env").is_file()
    assert not (files / ".env.example").exists()
    assert (files / "config" / "qweather_private_key.pem").is_file()
    assert (
        files / "core" / "character" / "configs" / "extra" / "2026" / "09" / "distilled_profile.md"
    ).is_file()


def test_study_tree_is_backed_up(tmp_path):
    repo = tmp_path / "repo"
    _make_repo(repo)
    study = tmp_path / "Study"
    _write(study / ".state" / "study_time.json", "{}")
    dest = tmp_path / "backup"
    auto_backup.run_backup(dest=dest, repo_root=repo, study_root=study, apply=True, now=NOW)
    assert (dest / "2026-07" / "Study" / ".state" / "study_time.json").is_file()


def test_dest_inside_source_rejected(tmp_path):
    repo = tmp_path / "repo"
    _make_repo(repo)
    with pytest.raises(ValueError):
        auto_backup.run_backup(dest=repo / "companion_data" / "bk", repo_root=repo, now=NOW)
