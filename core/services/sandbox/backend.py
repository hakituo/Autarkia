"""执行后端选择：按平台决定用容器还是进程级沙箱。

选择规则：

- **Windows**：一律进程级。Docker Desktop 在 Windows 上依赖 WSL2 / Hyper-V
  虚拟机，引入这层依赖不划算，而进程级沙箱已能覆盖本机使用。
- **Linux / macOS**：优先 Docker（内核级隔离，代码出不了容器）；
  探测不到 Docker 时回退进程级。

后端实现刻意保持可替换：``runner.py``（进程级）与 ``docker_runner.py``（容器）
返回同一个 :class:`SandboxResult`，上层（工具定义、AST 检查、产物回传）不感知差异。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional

from core.services.sandbox.runner import SandboxResult
from core.services.sandbox.runner import run_code as _run_process
from core.utils.logger import get_logger

logger = get_logger("SandboxBackend")

PROCESS_BACKEND = "process"
DOCKER_BACKEND = "docker"

_cached_backend: Optional[str] = None


def _docker_available() -> bool:
    """探测 docker CLI 是否可用且守护进程在跑。"""
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=8,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _detect_backend() -> str:
    if os.name == "nt":
        return PROCESS_BACKEND
    if _docker_available():
        return DOCKER_BACKEND
    return PROCESS_BACKEND


def resolve_backend(*, refresh: bool = False) -> str:
    """返回当前平台应使用的执行后端名。

    结果会缓存，避免每次执行都去探测一次 ``docker info``；
    装好 Docker 后重启进程即可生效（或传 ``refresh=True``）。
    """
    global _cached_backend
    if _cached_backend is None or refresh:
        _cached_backend = _detect_backend()
        logger.info("沙箱执行后端已选定: %s", _cached_backend)
    return _cached_backend


async def run_code(
    code: str,
    *,
    timeout: float = 30,
    keep_workdir: bool = False,
) -> SandboxResult:
    """统一执行入口：按平台自动路由到 Docker 或进程级后端。"""
    if resolve_backend() == DOCKER_BACKEND:
        from core.services.sandbox.docker_runner import run_code_docker

        return await run_code_docker(
            code, timeout=timeout, keep_workdir=keep_workdir
        )
    return await _run_process(code, timeout=timeout, keep_workdir=keep_workdir)
