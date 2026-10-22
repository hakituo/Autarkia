"""AST 静态安全检查：在代码进入沙箱执行前拦掉逃逸手法。

与 ``core/services/auto_heal/patch_sandbox.py`` 的关键区别：
后者只需要防止 **import 阶段** 执行副作用，因此只扫描模块级节点；
本模块的代码会被真正执行，所以必须 **递归遍历整棵语法树**——
函数体、类体、推导式里的危险调用同样会在运行时生效。

策略是白名单优先：只有显式列出的模块可以 import，其余一律拒绝。
"""

from __future__ import annotations

import ast
from typing import List, Tuple

# 允许 import 的模块根名。只列安全的计算 / 绘图 / 数据处理库；
# 任何能碰文件系统、网络、进程、解释器内部状态的模块都不在名单里。
ALLOWED_IMPORT_ROOTS = frozenset(
    {
        # 科学计算与绘图
        "numpy",
        "scipy",
        "pandas",
        "sympy",
        "matplotlib",
        "seaborn",
        "plotly",
        "PIL",
        "networkx",
        "statsmodels",
        # 安全的标准库子集
        "math",
        "cmath",
        "random",
        "statistics",
        "decimal",
        "fractions",
        "numbers",
        "operator",
        "itertools",
        "functools",
        "collections",
        "heapq",
        "bisect",
        "array",
        "copy",
        "datetime",
        "calendar",
        "time",
        "json",
        "csv",
        "re",
        "string",
        "textwrap",
        "unicodedata",
        "uuid",
        "hashlib",
        "hmac",
        "base64",
        "binascii",
        "zlib",
        "gzip",
        "struct",
        "typing",
        "dataclasses",
        "enum",
        "abc",
        "pprint",
        "difflib",
        "contextlib",
        "warnings",
        "traceback",
        "zoneinfo",
        "keyword",
        "graphlib",
    }
)

# 禁止直接调用的裸名。这些都是逃逸或读取解释器状态的标准入口。
FORBIDDEN_BARE_NAMES = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "input",
        "breakpoint",
        "globals",
        "locals",
        "vars",
        "dir",
        "getattr",
        "setattr",
        "delattr",
        "hasattr",
        "memoryview",
        "exit",
        "quit",
        "help",
        "print_to_console",
    }
)

# 禁止的属性访问链前缀（完整链匹配或后缀匹配）。
# 这些模块即使被间接拿到（例如通过某个对象的方法返回值）也不允许调用。
FORBIDDEN_ATTR_PREFIXES = (
    "os.",
    "sys.",
    "subprocess.",
    "socket.",
    "shutil.",
    "ctypes.",
    "importlib.",
    "builtins.",
    "threading.",
    "multiprocessing.",
    "concurrent.",
    "signal.",
    "pickle.",
    "marshal.",
    "shelve.",
    "dbm.",
    "sqlite3.",
    "pathlib.",
    "tempfile.",
    "glob.",
    "io.",
    "platform.",
    "resource.",
    "gc.",
    "inspect.",
    "code.",
    "codeop.",
    "compileall.",
    "runpy.",
    "pkgutil.",
    "pdb.",
    "webbrowser.",
    "urllib.",
    "http.",
    "ftplib.",
    "smtplib.",
    "telnetlib.",
    "requests.",
    "aiohttp.",
    "httpx.",
    "asyncio.",
    "atexit.",
    "fileinput.",
    "pty.",
    "tty.",
    "termios.",
    "fcntl.",
    "tkinter.",
    "antigravity.",
    "this.",
    "__builtins__.",
)

# 禁止访问的 dunder 属性名。这是从任意对象爬回解释器内核的经典路径，
# 例如 (1).__class__.__bases__[0].__subclasses__() 可以捞出 os 模块。
FORBIDDEN_ATTR_NAMES = frozenset(
    {
        "__class__",
        "__bases__",
        "__base__",
        "__subclasses__",
        "__mro__",
        "__globals__",
        "__code__",
        "__closure__",
        "__func__",
        "__self__",
        "__dict__",
        "__builtins__",
        "__import__",
        "__loader__",
        "__spec__",
        "__getattribute__",
        "__reduce__",
        "__reduce_ex__",
        "__getstate__",
        "__setstate__",
        "__init_subclass__",
        "__subclasshook__",
    }
)


def _attr_chain(node: ast.AST) -> str:
    """把属性访问节点还原成 ``a.b.c`` 形式的完整链，用于前缀匹配。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _attr_chain(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


class _GuardVisitor(ast.NodeVisitor):
    """递归遍历语法树，收集所有违规点。"""

    def __init__(self) -> None:
        self.errors: List[str] = []

    def _record(self, node: ast.AST, message: str) -> None:
        line = getattr(node, "lineno", 0)
        self.errors.append(f"第 {line} 行：{message}")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root not in ALLOWED_IMPORT_ROOTS:
                self._record(node, f"禁止导入模块 {alias.name}（不在白名单内）")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level and node.level > 0:
            self._record(node, "禁止相对导入")
            return
        module = node.module or ""
        root = module.split(".")[0]
        if root and root not in ALLOWED_IMPORT_ROOTS:
            self._record(node, f"禁止从模块 {module} 导入（不在白名单内）")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in FORBIDDEN_ATTR_NAMES:
            self._record(node, f"禁止访问属性 {node.attr}")
        else:
            chain = _attr_chain(node)
            if chain:
                for prefix in FORBIDDEN_ATTR_PREFIXES:
                    if chain == prefix.rstrip(".") or chain.startswith(prefix):
                        self._record(node, f"禁止访问 {chain}")
                        break
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in FORBIDDEN_BARE_NAMES:
                self._record(node, f"禁止调用 {func.id}()")
        elif isinstance(func, ast.Attribute):
            chain = _attr_chain(func)
            if chain:
                for prefix in FORBIDDEN_ATTR_PREFIXES:
                    if chain == prefix.rstrip(".") or chain.startswith(prefix):
                        self._record(node, f"禁止调用 {chain}()")
                        break
        self.generic_visit(node)


def check_code(code: str, *, max_errors: int = 8) -> Tuple[bool, List[str]]:
    """检查代码是否可以安全执行。

    Returns:
        ``(ok, errors)``。``ok`` 为 True 表示通过静态检查；
        ``errors`` 是面向模型的简短说明（最多 ``max_errors`` 条）。
    """
    if not str(code or "").strip():
        return False, ["代码为空"]

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, [f"语法错误：第 {exc.lineno} 行 {exc.msg}"]
    except Exception as exc:  # pragma: no cover - 解析器的极端异常
        return False, [f"代码解析失败：{exc}"]

    visitor = _GuardVisitor()
    visitor.visit(tree)
    if visitor.errors:
        return False, visitor.errors[:max_errors]
    return True, []
