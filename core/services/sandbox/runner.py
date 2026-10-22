"""沙箱执行器：在隔离子进程中运行 Python 代码，收集输出与产物文件。

安全边界（第一版，进程级）：
1. **最小环境变量**：子进程只继承解释器启动必需的变量，
   绝不传递 API key / 令牌 / 代理凭据。
2. **隔离模式**：以 ``-I`` 启动，忽略 PYTHONPATH 与 user site-packages。
3. **工作目录锁定**：子进程 cwd 指向独立临时目录，产物只能落在那里。
4. **超时强杀**：超时后 kill 子进程，避免死循环占住后端。

注意：Windows 上既没有 ``resource`` 模块也没有 namespace/seccomp，
本层能防住误用与常见逃逸，但不等同于容器级隔离。
执行后端刻意保持可替换，后续接入容器时只需替换 :func:`run_code`。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from core.utils.logger import get_logger

logger = get_logger("SandboxRunner")

DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 120.0
MAX_OUTPUT_CHARS = 8000
MAX_ARTIFACTS = 20
MAX_ARTIFACT_BYTES = 20 * 1024 * 1024

# 只保留解释器启动所必需的环境变量。刻意不传 PATH 以外的任何凭据类变量。
_ENV_ALLOWLIST = (
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "PATH",
    "TEMP",
    "TMP",
    "PATHEXT",
    "NUMBER_OF_PROCESSORS",
)

# 绘图后端必须在导入 pyplot 之前设定，否则无头环境会报错。
_PRELUDE = (
    "try:\n"
    "    import matplotlib\n"
    "    matplotlib.use('Agg')\n"
    "except Exception:\n"
    "    pass\n"
)


@dataclass
class SandboxResult:
    """一次沙箱执行的完整结果。"""

    ok: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    timed_out: bool = False
    artifacts: List[str] = field(default_factory=list)
    workdir: str = ""
    error: str = ""


def _project_root() -> Path:
    try:
        from core.utils.common import get_project_root

        return Path(get_project_root())
    except Exception:
        return Path(__file__).resolve().parents[3]


def _build_env(workdir: Path) -> dict:
    """构造最小化环境变量，避免向子进程泄露敏感信息。

    注意：环境变量被裁剪后 ``HOME`` / ``USERPROFILE`` 不再存在，
    而 matplotlib 需要一个可写的配置目录，否则 import 阶段就会失败。
    这里把配置目录指进沙箱工作目录，既不依赖用户主目录，也不向外泄露路径。
    """
    env = {key: os.environ[key] for key in _ENV_ALLOWLIST if key in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["MPLBACKEND"] = "Agg"
    env["MPLCONFIGDIR"] = str(workdir / ".mplconfig")
    return env


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[输出已截断，共 {len(text)} 字符]"


def _collect_artifacts(workdir: Path, dest: Path) -> List[str]:
    """把工作目录里的产物文件拷到持久目录，返回新路径列表。"""
    artifacts: List[str] = []
    dest.mkdir(parents=True, exist_ok=True)
    for item in sorted(workdir.iterdir()):
        if not item.is_file() or item.name == "main.py":
            continue
        if len(artifacts) >= MAX_ARTIFACTS:
            break
        try:
            if item.stat().st_size > MAX_ARTIFACT_BYTES:
                continue
            target = dest / item.name
            shutil.copy2(item, target)
            artifacts.append(str(target))
        except Exception as exc:
            logger.warning("收集产物失败 %s: %s", item.name, exc)
    return artifacts


async def run_code(
    code: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    keep_workdir: bool = False,
) -> SandboxResult:
    """在隔离子进程中执行 ``code``。

    Args:
        code: 待执行的 Python 源码（应已通过 ``ast_guard.check_code``）。
        timeout: 超时秒数，超过后强杀子进程。
        keep_workdir: 调试用；为 True 时不清理临时工作目录。

    Returns:
        :class:`SandboxResult`
    """
    try:
        effective_timeout = max(1.0, min(float(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    except (TypeError, ValueError):
        effective_timeout = DEFAULT_TIMEOUT

    run_id = uuid.uuid4().hex[:12]
    workdir = Path(tempfile.mkdtemp(prefix=f"xy_sandbox_{run_id}_"))
    script_path = workdir / "main.py"
    try:
        script_path.write_text(_PRELUDE + (code or ""), encoding="utf-8")
    except Exception as exc:
        return SandboxResult(ok=False, workdir=str(workdir), error=f"写入脚本失败：{exc}")

    proc = None
    timed_out = False
    stdout_raw = b""
    stderr_raw = b""
    exit_code: Optional[int] = None
    error = ""

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(script_path),
            cwd=str(workdir),
            env=_build_env(workdir),
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
        exit_code = proc.returncode
    except Exception as exc:
        error = f"启动子进程失败：{exc}"
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
        error = f"执行超时（超过 {effective_timeout:.0f} 秒），已终止"

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
