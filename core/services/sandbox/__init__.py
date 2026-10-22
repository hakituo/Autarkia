"""代码执行沙箱。

对外暴露三个入口：

- :func:`check_code` —— 执行前的 AST 静态检查（递归全树白名单）
- :func:`run_code` —— 统一执行入口，按平台自动选后端
- :func:`resolve_backend` —— 查询当前平台会用的后端（``process`` / ``docker``）

后端选择：

- Windows → 进程级（不引入 WSL2 / Hyper-V 依赖）
- Linux / macOS → 优先 Docker（内核级隔离），探测不到时回退进程级

典型用法::

    from core.services.sandbox import check_code, run_code

    ok, errors = check_code(code)
    if not ok:
        return "代码被安全检查拒绝：" + "；".join(errors)
    result = await run_code(code, timeout=30)
"""

from core.services.sandbox.ast_guard import check_code
from core.services.sandbox.backend import resolve_backend, run_code
from core.services.sandbox.runner import SandboxResult

__all__ = ["check_code", "run_code", "resolve_backend", "SandboxResult"]
