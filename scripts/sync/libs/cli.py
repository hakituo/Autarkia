"""组件库同步命令行。

    python scripts/sync/libs_sync.py status
    python scripts/sync/libs_sync.py task
    python scripts/sync/libs_sync.py push
    python scripts/sync/libs_sync.py mirror
    python scripts/sync/libs_sync.py baseline

``status/task`` 只读；``push/baseline/ack/mirror`` 会改仓库或状态。
"""

from __future__ import annotations

import argparse
import sys

from scripts.sync.libs import drift as drift_mod
from scripts.sync.libs import gitops, tasks
from scripts.sync.libs.manifest import Manifest, load_manifest
from scripts.sync.libs.publish import sync_libs
from scripts.sync.libs.state import SyncState


def _load() -> tuple[Manifest, SyncState]:
    manifest = load_manifest()
    return manifest, SyncState(manifest.state_dir).load()


def cmd_status(_args: argparse.Namespace) -> int:
    manifest, state = _load()
    drifts = drift_mod.compute_drift(manifest, state)
    print(f"[组件库] 根目录: {manifest.libs_root}")
    print(f"[组件库] 基线: {state.path}")
    if manifest.peer_root is None:
        print("[组件库] 对端: 当前系统读不到另一侧磁盘")
    else:
        print(f"[组件库] 对端: {manifest.peer_root}")

    for drift in drifts:
        spec = drift.spec
        repo = manifest.repo(spec)
        if not gitops.is_repo(repo):
            print(f"  - {spec.name}: 仓库缺失 ({repo})")
            continue
        dirty = len(gitops.changed_files(repo))
        ahead = gitops.ahead_of_origin(repo) if spec.published else 0
        counts = drift.counts()
        publish = "GitHub+PyPI" if spec.published else "本地"
        mirror = _mirror_label(manifest, spec, repo)
        print(
            f"  - {spec.name}: {publish} 工作树={dirty} 未推送={ahead} "
            f"主→库={counts.get('to_lib', 0)} 库→主={counts.get('to_main', 0)} "
            f"冲突={counts.get('conflict', 0)} 基线={counts.get('baseline', 0)} 对端={mirror}"
        )

    pending = state.root / "pending"
    if pending.is_dir() and any(pending.glob("*.md")):
        print(f"[组件库] 待办目录: {pending}")
        for path in sorted(pending.glob("*.md")):
            print(f"  - {path.name}（python scripts/sync/libs_sync.py task 查看）")
    return 0


def _mirror_label(manifest: Manifest, spec, repo) -> str:
    peer = manifest.peer_repo(spec)
    if peer is None:
        return "不可读"
    if not gitops.is_repo(peer):
        return "缺失"
    local_head, peer_head = gitops.head(repo), gitops.head(peer)
    if local_head == peer_head:
        return "一致" if gitops.is_clean(peer) else "提交一致/工作树脏"
    if gitops.is_ancestor(repo, peer_head, local_head):
        return "Windows 落后"
    if gitops.is_ancestor(repo, local_head, peer_head):
        return "Windows 领先"
    return "分叉"


def cmd_detect(args: argparse.Namespace) -> int:
    manifest, _state = _load()
    hits = manifest.main_to_libs(args.paths or [])
    if not hits:
        print("[组件库] 本次主仓变更未命中任何组件库映射")
        return 0
    for name, mappings in sorted(hits.items()):
        spec = manifest.get(name)
        repo = manifest.repo(spec)
        dirty = len(gitops.changed_files(repo)) if gitops.is_repo(repo) else -1
        print(f"[组件库] {name}: 命中 {len(mappings)} 个文件，组件库工作树改动={dirty}")
        for mapping in mappings:
            print(f"  - {mapping.lib} ← {', '.join(mapping.main)}")
    return 0


def cmd_task(args: argparse.Namespace) -> int:
    manifest, state = _load()
    drifts = drift_mod.compute_drift(manifest, state)
    written = tasks.write_pending(drifts, manifest, state)
    for path in written:
        print(f"[组件库] {path}")
        if not args.quiet:
            print(path.read_text(encoding="utf-8"))
    if not written and not args.quiet:
        print("[组件库] 没有需要移植的方向")
    return 0


def cmd_push(args: argparse.Namespace) -> int:
    report = sync_libs(
        changed_main=args.path or [],
        summary=args.message or "",
        dry_run=args.dry_run,
        run_tests=not args.no_tests,
        pypi_enabled=args.pypi,
        only=args.only,
        strict=args.strict,
    )
    if report.warnings:
        for warning in report.warnings:
            print(f"[组件库] 警告: {warning}")
    return 0 if report.ok else 1


def cmd_mirror(_args: argparse.Namespace) -> int:
    manifest, _state = _load()
    if manifest.peer_root is None:
        print("[组件库] 当前系统没有可读对端，跳过磁盘镜像")
        return 0
    failed = 0
    for spec in manifest.libs:
        repo = manifest.repo(spec)
        peer = manifest.peer_repo(spec)
        if not gitops.is_repo(repo) or peer is None or not gitops.is_repo(peer):
            print(f"[组件库] {spec.name}: 仓库缺失，跳过")
            continue
        result = gitops.mirror(repo, peer)
        print(f"[组件库] {spec.name}: {result.status} {result.detail}".rstrip())
        if result.status in {"blocked", "error", "diverged"}:
            failed += 1
    return 1 if failed else 0


def cmd_baseline(args: argparse.Namespace) -> int:
    manifest, state = _load()
    for spec in manifest.libs:
        if args.only is not None and spec.name not in args.only:
            continue
        repo = manifest.repo(spec)
        if not gitops.is_repo(repo):
            print(f"[组件库] {spec.name}: 仓库缺失，跳过")
            continue
        state.record_all(manifest, repo, spec)
        print(f"[组件库] {spec.name}: 基线已记录")
    print(f"[组件库] 状态文件: {state.path}")
    return 0


def cmd_ack(args: argparse.Namespace) -> int:
    manifest, state = _load()
    spec = manifest.get(args.lib)
    repo = manifest.repo(spec)
    if not gitops.is_repo(repo):
        print(f"[组件库] {spec.name}: 仓库缺失")
        return 1
    state.record_all(manifest, repo, spec)
    print(f"[组件库] {spec.name}: 已确认双向一致并更新基线")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autarkia 组件库双向同步")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="查看漂移、GitHub 未推送与 Windows 镜像状态")
    detect = sub.add_parser("detect", help="检测主仓变更命中了哪些组件库")
    detect.add_argument("--paths", nargs="*", default=[])

    task = sub.add_parser("task", help="生成/查看双向移植任务")
    task.add_argument("--quiet", action="store_true")

    push = sub.add_parser("push", help="提交并推送组件库改动（含测试门禁）")
    push.add_argument("--only", nargs="*", default=None, help="只处理指定组件库")
    push.add_argument("--path", nargs="*", default=[], help="主仓变更文件（用于检测漏同步）")
    push.add_argument("-m", "--message", default="", help="单行提交摘要")
    push.add_argument("--dry-run", action="store_true")
    push.add_argument("--no-tests", action="store_true")
    push.add_argument("--pypi", action="store_true", help="版本变化时发布 PyPI")
    push.add_argument("--strict", action="store_true", help="漏同步时返回失败")

    sub.add_parser("mirror", help="Linux ↔ Windows 磁盘仓库快进同步")

    baseline = sub.add_parser("baseline", help="建立/刷新同步基线")
    baseline.add_argument("--only", nargs="*", default=None)

    ack = sub.add_parser("ack", help="确认某个库已双向一致并更新基线")
    ack.add_argument("--lib", required=True)
    return parser


HANDLERS = {
    "status": cmd_status,
    "detect": cmd_detect,
    "task": cmd_task,
    "push": cmd_push,
    "mirror": cmd_mirror,
    "baseline": cmd_baseline,
    "ack": cmd_ack,
}


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    return HANDLERS[args.command](args)
