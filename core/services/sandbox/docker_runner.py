"""Docker 后端：内核级隔离执行（Linux / macOS 使用）。

与进程级后端的差别：

- **文件系统**：容器根只读，只挂载工作目录，代码写不到宿主机其他位置
- **网络**：``--network none``，代码完全断网
- **资源**：内存 / CPU / 进程数都有硬上限，fork 炸弹与内存炸弹失效
- **权限**：``--cap-drop ALL`` + ``no-new-privileges``

镜像需要预装代码要用的库，见根目录 ``Dockerfile.sandbox``。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import List, Optional

from core.services.sandbox.runner import (
    DEFAULT_TIMEOUT,
    MAX_TIMEOUT,
    SandboxResult,
    _collect_artifacts,
    _project_root,
    _truncate,
)
from core.utils.logger import get_logger

logger = get_logger("SandboxDocker")

DEFAULT_IMAGE = os.getenv("XIAOYOU_SANDBOX_IMAGE", "xiaoyou-sandbox:latest")
MEMORY_LIMIT = os.getenv("XIAOYOU_SANDBOX_MEMORY", "512m")
CPU_LIMIT = os.getenv("XIAOYOU_SANDBOX_CPUS", "1")
PIDS_LIMIT = os.getenv("XIAOYOU_SANDBOX_PIDS", "64")
TMPFS_SIZE = os.getenv("XIAOYOU_SANDBOX_TMPFS", "64m")

_PRELUDE = (
    "try:\n"
    "    import matplotlib\n"
    "    matplotlib.use('Agg')\n"
    "except Exception:\n"
    "    pass\n"
)


def _build_docker_cmd(workdir: Path, container_name: str, image: str) -> List[str]:
    """构造 ``docker run`` 参数。

    抽成独立函数，便于单测逐条校验安全开关是否都在。
    """
    return [
        "docker", "run", "--rm",
        "--name", container_name,
        "--network", "none",
        "--memory", MEMORY_LIMIT,
        "--cpus", CPU_LIMIT,
        "--pids-limit", PIDS_LIMIT,
        "--read-only",
        "--tmpfs", f"/tmp:rw,size={TMPFS_SIZE}",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "-v", f"{workdir.as_posix()}:/work:rw",
        "-w", "/work",
        "-e", "MPLBACKEND=Agg",
        "-e", "MPLCONFIGDIR=/work/.mplconfig",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-e", "PYTHONIOENCODING=utf-8",
        image,
        "python", "/work/main.py",
    ]


async def _kill_container(container_name: str) -> None:
    """超时后强制清理容器。

    ``docker run --rm`` 只在客户端正常退出时删容器；客户端被 kill 后
    容器会继续跑，必须显式 ``docker kill``。
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "kill", container_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=10)
    except Exception as exc:
        logger.warning("清理容器 %s 失败: %s", container_name, exc)


async def run_code_docker(
    code: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    keep_workdir: bool = False,
    image: Optional[str] = None,
) -> SandboxResult:
    """在 Docker 容器中执行 ``code``，返回与进程级后端一致的结果结构。"""
    try:
        effective_timeout = max(1.0, min(float(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    except (TypeError, ValueError):
        effective_timeout = DEFAULT_TIMEOUT

    run_id = uuid.uuid4().hex[:12]
    container_name = f"xy_sandbox_{run_id}"
    workdir = Path(tempfile.mkdtemp(prefix=f"xy_sandbox_{run_id}_"))
    script_path = workdir / "main.py"
    try:
        script_path.write_text(_PRELUDE + (code or ""), encoding="utf-8")
    except Exception as exc:
        return SandboxResult(
            ok=False, workdir=str(workdir), error=f"写入脚本失败：{exc}"
        )

    cmd = _build_docker_cmd(workdir, container_name, image or DEFAULT_IMAGE)
    proc = None
    timed_out = False
    stdout_raw = b""
    stderr_raw = b""
    exit_code: Optional[int] = None
    error = ""

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_raw, stderr_raw = await asyncio.wait_for(
                proc.communicate(), timeout=effective_timeout
            )
        except asyncio.TimeoutError:
            timed_out = True
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await proc.wait()
            except Exception:
                pass
            await _kill_container(container_name)
        exit_code = proc.returncode
    except Exception as exc:
        error = f"启动容器失败：{exc}"
    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except Exception:
                pass

    stdout = _truncate(stdout_raw.decode("utf-8", errors="replace"))
    stderr = _truncate(stderr_raw.decode("utf-8", errors="replace"))

    dest = _project_root() / "output" / "sandbox" / run_id
    artifacts = _collect_artifacts(workdir, dest)

    if not keep_workdir:
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass

    ok = (not timed_out) and (not error) and exit_code == 0
    if timed_out:
        error = f"执行超时（超过 {effective_timeout:.0f} 秒），容器已终止"

    return SandboxResult(
        ok=ok,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        timed_out=timed_out,
        artifacts=artifacts,
        workdir=str(workdir),
        error=error,
    )
