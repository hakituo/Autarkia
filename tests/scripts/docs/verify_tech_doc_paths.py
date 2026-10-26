"""校验技术参考文档里引用的仓库路径与相对链接是否真实存在。

背景：技术参考最大的腐烂方式是「文件早删了、文档还写着」。2026-10 实测拆分前的
单文件里 189 条带目录的文件引用中 42 条指向不存在的路径（`core/model_adapter.py`、
`clients/bots/dual_qq_adapter.py` 等），而且没有任何检查会在改代码时提醒。

检查两件事：

1. 反引号里的仓库相对路径（`` `core/services/aveline/service.py` ``）必须存在；
2. Markdown 相对链接（`](tech/memory.md)`）解析后必须存在（外链与纯锚点跳过）。

只查 `.trae/context/` 与 `docs/technical_reference/`，不扫全仓文档 —— 其它 README
里的历史引用不在本脚本职责内。

防噪音规则：含占位符（`<`、`*`、`YYYY`、`...`、`xxx` 等）的片段直接跳过；存量失效
登记在 `tech_doc_path_baseline.txt`，只对**新增**失效报错（与行数审计同款策略）。

运行：

    venv_cpu\\Scripts\\python.exe tests\\scripts\\docs\\verify_tech_doc_paths.py
    venv_cpu\\Scripts\\python.exe tests\\scripts\\docs\\verify_tech_doc_paths.py --verbose
    venv_cpu\\Scripts\\python.exe tests\\scripts\\docs\\verify_tech_doc_paths.py --update-baseline
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASELINE_PATH = Path(__file__).with_name("tech_doc_path_baseline.txt")

DOC_ENTRY_FILES = [
    ROOT / ".trae" / "context" / "TECHNICAL_REFERENCE.md",
    ROOT / ".trae" / "context" / "DECISION_TREE.md",
    ROOT / ".trae" / "context" / "CONTEXT_ROUTER.md",
    ROOT / ".trae" / "context" / "CODING_GUIDE.md",
    ROOT / ".trae" / "context" / "ARCHITECTURE.md",
]
DOC_DIRS = [
    ROOT / ".trae" / "context" / "tech",
    ROOT / ".trae" / "context" / "decisions",
    ROOT / ".trae" / "context" / "routing",
    ROOT / ".trae" / "context" / "coding",
    ROOT / ".trae" / "context" / "arch",
    ROOT / "docs" / "technical_reference",
]

CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
MD_LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
LINE_SUFFIX_RE = re.compile(r":\d+(?:-\d+)?$")

# 片段里出现这些字符/词就认定是模板或示例，不当作真实路径
PLACEHOLDER_TOKENS = (
    "<",
    ">",
    "*",
    "?",
    "{",
    "}",
    "$",
    "|",
    "~",
    "...",
    "YYYY",
    "yyyy",
    "MM",
    "DD",
    "xxx",
    "Xxx",
    "示例",
    "任意",
)

# 这些后缀/形态视为「路径」而不是普通代码片段
PATH_SUFFIXES = (".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt", ".kt", ".ts", ".tsx", ".sh", ".bat")


def _top_dirs() -> set[str]:
    names = {p.name for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith(".")}
    names |= {".trae", ".github"}
    return names


def _iter_docs() -> list[Path]:
    docs = [path for path in DOC_ENTRY_FILES if path.is_file()]
    for base in DOC_DIRS:
        if base.is_dir():
            docs.extend(sorted(base.rglob("*.md")))
    return docs


# 运行时生成、不入库的路径前缀（日志、虚拟环境、构建产物）
RUNTIME_PREFIXES = ("logs/", "output/", "companion_data/", ".cache/")

# 故意保留的「已删除」说明：文档正文在讲这个文件已经不在了，路径不存在是预期结果
EXEMPT_TARGETS = {
    "core/core_engine/engine.py",
}


def _is_candidate(span: str, top_dirs: set[str]) -> bool:
    if not span or " " in span or any(token in span for token in PLACEHOLDER_TOKENS):
        return False
    if "/" not in span:
        return False
    first = span.split("/", 1)[0]
    if first not in top_dirs:
        return False
    # 只校验「有扩展名的文件路径」：纯目录引用大量是包内相对路径（如 Android 的
    # services/foreground），按仓库根判定必然误报
    base = span.split("::", 1)[0].split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return "." in base and not span.endswith("/")


def _norm(span: str) -> str:
    """去掉 `::函数名` / `#锚点` / `:行号` 后缀，只留文件路径。"""
    path = span.split("::", 1)[0].split("#", 1)[0].strip().rstrip("/")
    return LINE_SUFFIX_RE.sub("", path)


def collect_missing(verbose: bool = False) -> list[tuple[str, str]]:
    """返回 [(文档相对路径, 失效引用)]。"""
    top_dirs = _top_dirs()
    missing: list[tuple[str, str]] = []

    for doc in _iter_docs():
        rel_doc = doc.relative_to(ROOT).as_posix()
        text = doc.read_text(encoding="utf-8")

        for match in CODE_SPAN_RE.finditer(text):
            span = match.group(1).strip()
            if not _is_candidate(span, top_dirs):
                continue
            target = _norm(span)
            if not target or target.startswith(RUNTIME_PREFIXES) or target in EXEMPT_TARGETS:
                continue
            if not (ROOT / target).exists():
                missing.append((rel_doc, target))

        for match in MD_LINK_RE.finditer(text):
            link = match.group(1).strip()
            if link.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if any(token in link for token in PLACEHOLDER_TOKENS):
                continue
            target = link.split("#", 1)[0]
            if not target:
                continue
            resolved = (doc.parent / target).resolve()
            if not resolved.exists():
                missing.append((rel_doc, f"{target} (链接)"))

    if verbose:
        for rel_doc, target in missing:
            print(f"  MISS {rel_doc} :: {target}")
    return missing


def load_baseline() -> set[str]:
    if not BASELINE_PATH.is_file():
        return set()
    entries: set[str] = set()
    for line in BASELINE_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entries.add(line.split("#", 1)[0].strip())
    return entries


def write_baseline(entries: list[tuple[str, str]]) -> None:
    lines = [
        "# 技术参考文档里的存量失效路径（只许减少，不许新增）",
        "# 由 `verify_tech_doc_paths.py --update-baseline` 生成；新增失效应修路径或删引用，而不是往这里加。",
        "# 格式：<文档> :: <失效引用>",
    ]
    lines += sorted(f"{rel_doc} :: {target}" for rel_doc, target in entries)
    BASELINE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="校验技术参考文档的路径与链接")
    parser.add_argument("--verbose", action="store_true", help="打印全部失效项")
    parser.add_argument("--update-baseline", action="store_true", help="把当前失效项写进基线")
    args = parser.parse_args()

    missing = collect_missing(verbose=args.verbose)
    unique = sorted({f"{rel_doc} :: {target}" for rel_doc, target in missing})

    if args.update_baseline:
        write_baseline([tuple(item.split(" :: ", 1)) for item in unique])  # type: ignore[misc]
        print(f"基线已更新：{len(unique)} 项")
        return 0

    baseline = load_baseline()
    new_items = [item for item in unique if item not in baseline]
    fixed_items = sorted(item for item in baseline if item not in set(unique))

    print("=" * 56)
    print("技术参考文档路径校验")
    print("=" * 56)
    print(f"扫描文档 {len(_iter_docs())} 份，失效引用 {len(unique)} 项（存量 {len(baseline)} 项）")

    if fixed_items:
        print(f"[基线可移除] {len(fixed_items)} 项已修复，可跑 --update-baseline 收缩")
        for item in fixed_items[:10]:
            print(f"  INFO {item}")

    if new_items:
        print(f"\n[新增失效] {len(new_items)} 项：")
        for item in new_items:
            print(f"  FAIL {item}")
        print("\n修法：把路径改成真实位置，或删掉该引用；不要往基线里加新条目。")
        return 1

    print("\n校验通过（无新增失效）✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
