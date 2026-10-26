"""验证 Linux 下 scheduler_py 的共享库查找（RUNPATH + 预加载兜底）。

背景（2026-10-25）：
CMake 曾把编译时的绝对路径 `/home/user/xiaoyou-core/...` 写进 RUNPATH；项目
目录搬迁到 Autarkia 后 RUNPATH 失效，导入时报
``libllama.so.0: cannot open shared object file``。处理分两层：
1) 重新编译，让 RUNPATH 写成本仓库路径（主路径，已用 readelf 校验不含旧路径）；
2) scheduler_wrapper 导入前用 ``ctypes.CDLL(RTLD_GLOBAL)`` 预加载扩展同级
   ``bin/`` 下的 .so（兜底，防止再次搬迁目录）。

验证方式：AST 静态检查 + RUNPATH 检查 + 真实导入（无编译产物或非 Linux 时跳过运行时部分）。
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WRAPPER_FILE = PROJECT_ROOT / "core" / "services" / "scheduler" / "scheduler_wrapper.py"
BUILD_DIR = PROJECT_ROOT / "cpp_modules" / "cpp_scheduler" / "build"
STALE_PATH_MARKERS = ("xiaoyou-core",)


def _functions() -> tuple[str, dict[str, ast.FunctionDef]]:
    source = WRAPPER_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(WRAPPER_FILE))
    funcs = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    return source, funcs


def check_source() -> list[str]:
    """预加载函数存在、使用 RTLD_GLOBAL，且导入流程在 posix 下调用它。"""
    issues: list[str] = []
    source, funcs = _functions()

    preload = funcs.get("_preload_posix_shared_libs")
    if preload is None:
        return ["scheduler_wrapper.py 缺少 _preload_posix_shared_libs"]

    segment = ast.get_source_segment(source, preload) or ""
    if "RTLD_GLOBAL" not in segment:
        issues.append("预加载未使用 RTLD_GLOBAL")
    if 'os.path.join(directory, "bin")' not in segment:
        issues.append("预加载未覆盖扩展同级 bin/ 目录")
    if ".so" not in segment or "scheduler_py" not in segment:
        issues.append("预加载未按 .so 过滤或未排除扩展本体")

    import_func = funcs.get("_import_scheduler_py")
    if import_func is None:
        return issues + ["scheduler_wrapper.py 缺少 _import_scheduler_py"]

    import_segment = ast.get_source_segment(source, import_func) or ""
    if "_preload_posix_shared_libs(path)" not in import_segment:
        issues.append("导入流程未调用 _preload_posix_shared_libs(path)")
    if 'os.name == "posix"' not in import_segment:
        issues.append("导入流程缺少 posix 分支判断")
    return issues


def check_artifact_runpath() -> list[str]:
    """编译产物的 RUNPATH 必须指向本仓库 build/bin，且不含搬迁前的旧路径。"""
    if os.name != "posix":
        return []
    extensions = sorted(BUILD_DIR.glob("scheduler_py*.so"))
    if not extensions:
        print("  提示: 无编译产物，跳过 RUNPATH 检查")
        return []
    readelf = shutil.which("readelf")
    if not readelf:
        print("  提示: 未找到 readelf，跳过 RUNPATH 检查")
        return []

    issues: list[str] = []
    for ext in extensions:
        result = subprocess.run(
            [readelf, "-d", str(ext)], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            issues.append(f"readelf 读取失败: {ext.name}")
            continue
        runpath_lines = [
            line
            for line in result.stdout.splitlines()
            if "RUNPATH" in line or "RPATH" in line
        ]
        if not runpath_lines:
            issues.append(f"扩展缺少 RUNPATH: {ext.name}")
            continue
        joined = "\n".join(runpath_lines)
        for marker in STALE_PATH_MARKERS:
            if marker in joined:
                issues.append(f"RUNPATH 仍含旧路径 {marker}: {ext.name}")
        if str(BUILD_DIR / "bin") not in joined:
            issues.append(f"RUNPATH 未指向 {BUILD_DIR / 'bin'}: {ext.name}")
    return issues


def check_bare_import() -> list[str]:
    """不借助预加载、只靠 RUNPATH 导入扩展（证明重编后的主路径生效）。"""
    if os.name != "posix" or not list(BUILD_DIR.glob("scheduler_py*.so")):
        return []
    code = (
        "import sys;"
        f"sys.path.insert(0, {str(BUILD_DIR)!r});"
        "import scheduler_py;"
        "print(scheduler_py.__file__)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return [f"裸 RUNPATH 导入失败: {result.stderr.strip().splitlines()[-1:]}"]
    return []


def check_runtime() -> list[str]:
    """真实导入 scheduler_py，并确认 libllama.so.0 来自 build/bin。"""
    if os.name != "posix":
        print("  提示: 非 Linux 平台，跳过运行时检查")
        return []
    if not BUILD_DIR.exists():
        print(f"  提示: 缺少编译产物 {BUILD_DIR}，跳过运行时检查")
        return []

    root = str(PROJECT_ROOT)
    sys.path.insert(0, root)
    try:
        from core.services.scheduler import scheduler_wrapper as sw  # noqa: PLC0415

        module = sw._get_scheduler_py()
        if module is None:
            return ["运行时导入 scheduler_py 失败"]
        if not sw.is_cpp_scheduler_available():
            return ["is_cpp_scheduler_available() 返回 False"]

        maps = Path("/proc/self/maps").read_text(encoding="utf-8")
        if "libllama.so.0" not in maps:
            return ["进程内未加载 libllama.so.0"]
        if str(BUILD_DIR / "bin") not in maps:
            return [f"libllama.so.0 不是从 {BUILD_DIR / 'bin'} 加载"]
        return []
    finally:
        if root in sys.path:
            sys.path.remove(root)


def _print_issues(issues: list[str]) -> None:
    print("发现以下问题:")
    for issue in issues:
        print(f"  ✗ {issue}")


def main() -> int:
    print("=== 验证: Linux scheduler_py 共享库查找（RUNPATH + 预加载兜底） ===")

    issues = check_source()
    if issues:
        _print_issues(issues)
        return 1
    print("✓ 源码含 RTLD_GLOBAL 预加载，并在导入前按 posix 分支调用")

    issues = check_artifact_runpath()
    if issues:
        _print_issues(issues)
        return 1
    print(f"✓ RUNPATH 指向 {BUILD_DIR / 'bin'} 且不含搬迁前旧路径")

    issues = check_bare_import()
    if issues:
        _print_issues(issues)
        return 1
    print("✓ 不依赖预加载，仅靠 RUNPATH 即可导入扩展")

    issues = check_runtime()
    if issues:
        _print_issues(issues)
        return 1

    print("✓ 运行时 scheduler_py 可导入，libllama.so.0 来自 build/bin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
