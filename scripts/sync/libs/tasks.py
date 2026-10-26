"""生成双向移植任务。

组件库是主仓代码的「通用化改写版」，不是逐字复制；语义移植交给 agent/人，
脚本负责把「哪边改了、改了什么、要对到哪个文件」整理成一份可直接执行的清单。
"""

from __future__ import annotations

import difflib
from pathlib import Path

from scripts.sync.libs.drift import FileDrift, LibDrift
from scripts.sync.libs.manifest import Manifest
from scripts.sync.libs.state import SyncState

DIFF_BUDGET = 160


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _diff(before: str, after: str, label: str) -> str:
    if before == after:
        return f"{label}: 内容未变化\n"
    lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"{label}（基线）",
            tofile=f"{label}（当前）",
            lineterm="",
        )
    )
    if len(lines) > DIFF_BUDGET:
        lines = lines[:DIFF_BUDGET] + [f"... 省略 {len(lines) - DIFF_BUDGET} 行"]
    return "\n".join(lines) + "\n"


def render(drift: LibDrift, manifest: Manifest, state: SyncState) -> str:
    """渲染一个组件库的待办说明。"""
    repo = manifest.repo(drift.spec)
    lines = [
        f"# {drift.spec.name} 同步任务",
        "",
        f"- 组件库路径：`{repo}`",
        f"- 主仓路径：`{manifest.project_root}`",
        f"- 规则提醒：改动前先读 `{repo / 'AGENTS.md'}`（宿主 import 禁止进 src/，语义以主仓为准）",
        "",
    ]
    for item in drift.files:
        if item.flag == "in_sync":
            continue
        lines.extend(_render_file(item, manifest, state))
    lines.extend(
        [
            "## 完成后",
            "",
            f"1. 在组件库跑测试：`PYTHONPATH=src python -m pytest -q`（工作目录 `{repo}`）",
            "2. 确认主仓与组件库语义一致后执行：",
            "",
            f"   `python scripts/sync/libs_sync.py ack --lib {drift.spec.name}`",
            "",
            "3. 再按 RULES.md §4 跑 `auto_commit_push.py`，两边会一起提交推送。",
            "",
        ]
    )
    return "\n".join(lines)


def _render_file(item: FileDrift, manifest: Manifest, state: SyncState) -> list[str]:
    direction = {
        "to_lib": "主仓 → 组件库",
        "to_main": "组件库 → 主仓",
        "conflict": "两侧都改了，需要合并",
        "baseline": "首次建立基线",
    }.get(item.flag, item.flag)
    lines = [f"## {direction}：`{item.mapping.lib}`", ""]
    lines.append("主仓源文件：" + "、".join(f"`{path}`" for path in item.mapping.main))
    lines.append("")
    if item.flag == "baseline":
        lines.append("还没有基线快照，本次只记录当前状态，不生成 diff。")
        lines.append("")
        return lines

    for source in item.mapping.main:
        before = state.read_base_main(item.spec.name, source)
        after = _read(manifest.project_root / source)
        if item.flag in {"to_lib", "conflict"}:
            lines.extend(["```diff", _diff(before, after, source).rstrip("\n"), "```", ""])

    if item.flag in {"to_main", "conflict"}:
        before = state.read_base_lib(item.spec.name, item.mapping.lib)
        after = _read(manifest.repo(item.spec) / item.mapping.lib)
        lines.extend(["```diff", _diff(before, after, item.mapping.lib).rstrip("\n"), "```", ""])

    lines.extend(
        [
            "移植要求：",
            "- 保留组件库已有的通用化改造（依赖注入、stdlib logger、无宿主 config/core/clients import）；",
            "- 只搬语义变化，不要把主仓的宿主耦合原样抄进去；",
            "- 行为判据以主仓为准，改完用组件库现有测试兜底。",
            "",
        ]
    )
    return lines


def write_pending(drifts: list[LibDrift], manifest: Manifest, state: SyncState) -> list[Path]:
    """把有待办的方向写到 ``<state>/pending/<lib>.md``，返回文件列表。"""
    pending_dir = state.root / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for drift in drifts:
        target = pending_dir / f"{drift.spec.name}.md"
        if not drift.pending and not drift.counts().get("baseline"):
            if target.exists():
                target.unlink()
            continue
        target.write_text(render(drift, manifest, state), encoding="utf-8", newline="\n")
        written.append(target)
    return written
