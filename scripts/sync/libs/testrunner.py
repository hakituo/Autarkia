"""组件库提交前的测试门禁。

不额外装虚拟环境：用主仓现有的 venv（RULES.md §2）跑组件库测试，
通过 ``PYTHONPATH=<repo>/src`` 让 src 布局直接可导入。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

TIMEOUT = 600


def test_python(project_root: Path) -> str:
    """按平台挑选主仓虚拟环境解释器，找不到才退回当前解释器。"""
    if os.name == "nt":
        candidates = [
            project_root / "venv_cpu" / "Scripts" / "python.exe",
            project_root / "venv_core" / "Scripts" / "python.exe",
        ]
    else:
        candidates = [
            project_root / "venv_cpu" / "bin" / "python",
            project_root / ".venv" / "bin" / "python",
        ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    import sys

    return sys.executable


def run_tests(repo: Path, project_root: Path) -> tuple[bool, str]:
    """跑组件库 pytest；没有 tests 目录视为跳过。"""
    if not (repo / "tests").is_dir():
        return True, "没有 tests 目录，跳过"
    cmd = [test_python(project_root), "-m", "pytest", "-q"]
    env = {
        **os.environ,
        "PYTHONPATH": str(repo / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_ADDOPTS": "",
    }
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"测试无法执行: {exc}"
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    summary = " | ".join(tail[-3:]) if tail else f"退出码 {proc.returncode}"
    return proc.returncode == 0, summary
