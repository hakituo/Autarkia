"""纯新增顶层符号的自动移植。

只处理最安全的一种情况：

- 与基线相比，源文件已有的顶层函数/类逐字未变；
- 只是多出了新的顶层函数/类；
- 新符号只引用目标模块已有的模块级名字（含 import）与内置名；
- 源文件与基线的 import 完全一致。

满足这些条件时把新符号追加到目标文件末尾。任何一条不满足都返回原因，
由上层生成移植任务，绝不猜测语义。
"""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass

DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
BUILTINS = set(dir(builtins))


@dataclass
class PortResult:
    text: str
    added: list[str]
    reason: str = ""


def port_additions(base: str, source: str, target: str) -> PortResult:
    """尝试把 ``source`` 相对 ``base`` 新增的顶层符号追加到 ``target``。"""
    if not base.strip() or not source.strip() or not target.strip():
        return PortResult(target, [], "缺少基线或文件内容")
    try:
        base_tree = ast.parse(base)
        source_tree = ast.parse(source)
        target_tree = ast.parse(target)
    except SyntaxError as exc:
        return PortResult(target, [], f"语法解析失败: {exc}")

    base_defs = _defs(base_tree)
    source_defs = _defs(source_tree)
    for name, node in base_defs.items():
        if name not in source_defs:
            return PortResult(target, [], f"删除了已有符号 {name}")
        if _norm(_segment(base, node)) != _norm(_segment(source, source_defs[name])):
            return PortResult(target, [], f"修改了已有符号 {name}")
    if _imports(base_tree) != _imports(source_tree):
        return PortResult(target, [], "import 发生变化，需要人工确认")

    new_names = [name for name in source_defs if name not in base_defs]
    if not new_names:
        return PortResult(target, [], "没有新增顶层符号")

    target_defs = _defs(target_tree)
    existing = [name for name in new_names if name in target_defs]
    if existing:
        return PortResult(target, [], f"目标已存在同名符号 {', '.join(existing)}")

    available = _module_names(target_tree)
    for name in new_names:
        node = source_defs[name]
        missing = _required(node) - _bound(node) - BUILTINS - available
        if missing:
            return PortResult(
                target, [], f"新增符号 {name} 依赖目标缺失的名字: {', '.join(sorted(missing))}"
            )
        available.add(name)

    block = "\n\n".join(_segment(source, source_defs[name]).strip("\n") for name in new_names)
    return PortResult(target.rstrip("\n") + "\n\n\n" + block + "\n", new_names)


def _defs(tree: ast.Module) -> dict[str, ast.AST]:
    return {node.name: node for node in tree.body if isinstance(node, DEFS)}


def _segment(text: str, node: ast.AST) -> str:
    lines = text.splitlines(keepends=True)
    decorators = getattr(node, "decorator_list", [])
    start = min([node.lineno, *[item.lineno for item in decorators]]) - 1
    return "".join(lines[start : node.end_lineno])


def _norm(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").splitlines()).strip()


def _imports(tree: ast.Module) -> tuple:
    result = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            result.append(("import", tuple(sorted(alias.name for alias in node.names))))
        elif isinstance(node, ast.ImportFrom):
            result.append(
                (
                    "from",
                    node.module,
                    node.level,
                    tuple(sorted((alias.name, alias.asname) for alias in node.names)),
                )
            )
    return tuple(result)


def _module_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, DEFS):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _bound(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.arg):
            names.add(sub.arg)
        elif isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
            names.add(sub.id)
        elif isinstance(sub, DEFS):
            names.add(sub.name)
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            for alias in sub.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(sub, ast.ExceptHandler) and sub.name:
            names.add(sub.name)
    return names


def _required(node: ast.AST) -> set[str]:
    return {
        sub.id
        for sub in ast.walk(node)
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load)
    }
