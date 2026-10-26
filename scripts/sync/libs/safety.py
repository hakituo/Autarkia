"""组件库提交前的敏感信息检查。

组件库是要推到 GitHub 的公开仓，检查范围只保留真实凭据类模式：
QQ 号、成人内容关键词属于主仓 private 场景，不在这里重复判断。
"""

from __future__ import annotations

from pathlib import Path

from scripts.git.auto_commit.sensitive_scan import CREDENTIAL_PATTERNS, SAFE_CONTEXTS
from scripts.sync.libs import gitops

SKIP_SUFFIXES = (
    ".example",
    ".sample",
    ".lock",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
)
SCAN_BUDGET = 5000


def scan_repo(repo: Path) -> list[dict]:
    """扫描组件库相对 HEAD 的新增行与未跟踪文本文件。"""
    changed = gitops.changed_files(repo)
    issues: list[dict] = []
    for name in changed:
        if name.endswith(SKIP_SUFFIXES):
            continue
        path = repo / name
        if not path.is_file():
            continue
        lines = _added_lines(repo, name) if _tracked(repo, name) else _all_lines(path)
        issues.extend(_scan(name, lines))
    return issues


def _tracked(repo: Path, name: str) -> bool:
    return gitops.run(repo, "cat-file", "-e", f"HEAD:{name}").returncode == 0


def _added_lines(repo: Path, name: str) -> list[tuple[int, str]]:
    proc = gitops.run(repo, "diff", "HEAD", "--", name)
    if proc.returncode != 0:
        return []
    lines: list[tuple[int, str]] = []
    new_line = 0
    for raw in proc.stdout.splitlines():
        if raw.startswith("@@"):
            try:
                new_line = int(raw.split("+", 1)[1].split(",", 1)[0].split(" ", 1)[0])
            except (IndexError, ValueError):
                new_line = 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            lines.append((new_line, raw[1:]))
            new_line += 1
        elif not raw.startswith("-"):
            new_line += 1
    return lines


def _all_lines(path: Path) -> list[tuple[int, str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return list(enumerate(text.splitlines()[:SCAN_BUDGET], 1))


def _scan(name: str, lines: list[tuple[int, str]]) -> list[dict]:
    issues: list[dict] = []
    for line_no, line in lines:
        for pattern, description in CREDENTIAL_PATTERNS:
            if not pattern.search(line):
                continue
            if any(context in line for context in SAFE_CONTEXTS):
                continue
            issues.append(
                {
                    "file": name,
                    "line": line_no,
                    "desc": description,
                    "content": line.strip()[:100],
                }
            )
    return issues
