"""已发布组件库的 PyPI 发布步骤。

只在 ``pyproject.toml`` 的版本号相对上次成功发布发生变化时才执行；
默认关闭，``--pypi`` 或 ``UV_PUBLISH_TOKEN`` 显式开启后才真正上传。
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from scripts.sync.libs.manifest import LibSpec
from scripts.sync.libs.state import SyncState


def read_version(repo: Path) -> str:
    try:
        text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else ""


def publish(repo: Path, spec: LibSpec, state: SyncState, *, enabled: bool, dry_run: bool) -> str:
    """返回一句人类可读的结果；不抛异常。"""
    version = read_version(repo)
    if not version:
        return "读不到版本号，跳过 PyPI"
    if version == state.version(spec.name):
        return f"版本 {version} 未变，跳过 PyPI"
    if not enabled:
        return f"版本 {version} 已变化，未发布（需要 --pypi）"
    if not os.environ.get("UV_PUBLISH_TOKEN"):
        return f"版本 {version} 已变化，缺少 UV_PUBLISH_TOKEN，未发布"
    if dry_run:
        return f"[DRY-RUN] 将发布 PyPI {version}"

    build = _run(["uv", "build"], repo)
    if build.returncode != 0:
        return f"uv build 失败: {_tail(build)}"
    upload = _run(["uv", "publish"], repo)
    if upload.returncode != 0:
        return f"uv publish 失败: {_tail(upload)}"
    state.set_version(spec.name, version)
    state.save()
    return f"已发布 PyPI {version}"


def _run(cmd: list[str], repo: Path) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            check=False,
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 1, "", str(exc))


def _tail(proc: subprocess.CompletedProcess) -> str:
    lines = (proc.stdout + proc.stderr).strip().splitlines()
    return " | ".join(lines[-2:]) if lines else f"退出码 {proc.returncode}"
