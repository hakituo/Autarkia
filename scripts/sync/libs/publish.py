"""组件库同步编排。

顺序固定为：检测漂移 → 凭据扫描 → 测试门禁 → 提交 → 推送 GitHub →
Windows 磁盘镜像 → 记录基线。任何一步失败都保留现场，不 force、不覆盖脏工作树。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from scripts.sync.libs import autotransfer, gitops, pypi, safety, tasks, testrunner
from scripts.sync.libs import drift as drift_mod
from scripts.sync.libs.manifest import LibSpec, Manifest, load_manifest
from scripts.sync.libs.state import SyncState

MESSAGE_MAX = 80


@dataclass
class LibsReport:
    ok: bool = True
    had_work: bool = False
    blocked: bool = False
    main_touched: bool = False
    touched: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    results: list[LibResult] = field(default_factory=list)


@dataclass
class LibResult:
    name: str
    dirty: int = 0
    committed: bool = False
    pushed: bool = False
    mirror: str = ""
    tests: str = ""
    pypi: str = ""


def sync_libs(
    *,
    changed_main: list[str] | None = None,
    summary: str = "",
    dry_run: bool = False,
    run_tests: bool = True,
    pypi_enabled: bool = False,
    only: list[str] | None = None,
    strict: bool = False,
    manifest: Manifest | None = None,
) -> LibsReport:
    """检测并同步组件库；返回是否成功、是否有实际工作。"""
    manifest = manifest or load_manifest()
    report = LibsReport()
    if not manifest.libs_root.is_dir():
        report.warnings = (f"组件库根目录不存在：{manifest.libs_root}",)
        print(f"[组件库] 跳过：{report.warnings[0]}")
        return report

    state = SyncState(manifest.state_dir).load()
    drifts = drift_mod.compute_drift(manifest, state)
    forward, reverse = autotransfer.apply(
        manifest, state, drifts, dry_run=dry_run, allow_reverse=only is None
    )
    report.main_touched = bool(reverse)
    if forward or reverse:
        drifts = drift_mod.compute_drift(manifest, state)
    touched = set(manifest.main_to_libs(changed_main or []))
    report.touched = tuple(sorted(touched))

    if touched:
        print(f"[组件库] 主仓变更命中 {len(touched)} 个库：{'、'.join(sorted(touched))}")
    for line in drift_mod.describe(drifts):
        print(f"[组件库] 漂移 {line}")

    by_name = {drift.spec.name: drift for drift in drifts}
    missing = _missing_ports(by_name, touched)
    if missing:
        print("[组件库] 警告：主仓已改，但组件库没有对应改动（疑似漏同步）：")
        for item in missing:
            print(f"  - {item}")
        report.warnings += tuple(missing)
        if strict:
            report.ok = False
            report.blocked = True
            print("[组件库] --strict-libs 已开启，终止本次流程")
            return report

    targets = _targets(manifest, by_name, touched, only)
    for spec in targets:
        try:
            result = _process_one(manifest, state, spec, summary, dry_run, run_tests, pypi_enabled)
        except _Abort as exc:
            report.ok = False
            report.warnings += (str(exc),)
            print(f"[组件库] 中止：{exc}")
            break
        report.results.append(result)
        report.had_work = (
            report.had_work
            or result.dirty > 0
            or result.committed
            or result.pushed
            or bool(result.mirror)
        )
        if result.mirror and result.mirror.split(" ", 1)[0] in {"blocked", "error", "diverged"}:
            report.warnings += (f"{spec.name}: Windows 镜像 {result.mirror}",)

    if not report.ok:
        report.blocked = True

    if not dry_run:
        state.save()
        after = drift_mod.compute_drift(manifest, state)
        written = tasks.write_pending(after, manifest, state)
        if written:
            print(f"[组件库] 已生成 {len(written)} 份待办：{state.root / 'pending'}")
            for path in written:
                print(f"  - {path.name}")
    return report


def _missing_ports(by_name: dict, touched: set[str]) -> list[str]:
    missing: list[str] = []
    for name in sorted(touched):
        drift = by_name.get(name)
        if drift is None:
            continue
        for item in drift.files_with("to_lib"):
            missing.append(f"{name}: {item.mapping.lib} ← {', '.join(item.mapping.main)}")
    return missing


def _targets(
    manifest: Manifest,
    by_name: dict,
    touched: set[str],
    only: list[str] | None,
) -> list[LibSpec]:
    selected: list[LibSpec] = []
    for spec in manifest.libs:
        if only is not None and spec.name not in only:
            continue
        repo = manifest.repo(spec)
        if not gitops.is_repo(repo):
            continue
        dirty = bool(gitops.porcelain(repo))
        ahead = gitops.ahead_of_origin(repo) if spec.published else 0
        drift = by_name.get(spec.name)
        has_pending = bool(drift and drift.pending)
        if dirty or ahead or spec.name in touched or has_pending:
            selected.append(spec)
    return selected


def _process_one(
    manifest: Manifest,
    state: SyncState,
    spec: LibSpec,
    summary: str,
    dry_run: bool,
    run_tests: bool,
    pypi_enabled: bool,
) -> LibResult:
    repo = manifest.repo(spec)
    result = LibResult(name=spec.name)
    dirty_files = gitops.changed_files(repo)
    result.dirty = len(dirty_files)
    ahead = gitops.ahead_of_origin(repo) if spec.published else 0

    if not dirty_files and not ahead:
        return result

    print(f"[组件库] {spec.name}: 改动 {result.dirty} 个文件，未推送提交 {ahead} 个")
    if dry_run:
        for name in dirty_files[:10]:
            print(f"  ~ {name}")
        if len(dirty_files) > 10:
            print(f"  ... 还有 {len(dirty_files) - 10} 个")
        print(f"  [DRY-RUN] 将提交并推送到 {'GitHub' if spec.published else '本地（未发布）'}")
        return result

    if dirty_files:
        issues = safety.scan_repo(repo)
        if issues:
            print(f"[组件库] {spec.name}: 发现 {len(issues)} 处疑似凭据，终止")
            for issue in issues[:10]:
                print(f"  - {issue['file']}:{issue['line']} [{issue['desc']}] {issue['content']}")
            raise _Abort(f"{spec.name} 敏感信息检查未通过")

        if run_tests and any(name.endswith(".py") for name in dirty_files):
            passed, detail = testrunner.run_tests(repo, manifest.project_root)
            result.tests = detail
            if not passed:
                print(f"[组件库] {spec.name}: 测试失败，未提交：{detail}")
                raise _Abort(f"{spec.name} 测试失败")

        message = _message(summary)
        committed, detail = gitops.commit_all(repo, message)
        if not committed:
            print(f"[组件库] {spec.name}: 提交失败：{detail}")
            raise _Abort(f"{spec.name} 提交失败")
        result.committed = True
        print(f"[组件库] {spec.name}: 已提交（{message}）")

    if spec.published:
        pushed, detail = gitops.push_origin(repo)
        result.pushed = pushed
        if not pushed:
            print(f"[组件库] {spec.name}: 推送 GitHub 失败：{detail}")
            raise _Abort(f"{spec.name} 推送失败")
        print(f"[组件库] {spec.name}: 已推送 GitHub")

    peer = manifest.peer_repo(spec)
    if peer is not None:
        mirrored = gitops.mirror(repo, peer)
        result.mirror = f"{mirrored.status} {mirrored.detail}".strip()
        print(f"[组件库] {spec.name}: Windows 镜像 {result.mirror}")

    if spec.pypi:
        result.pypi = pypi.publish(repo, spec, state, enabled=pypi_enabled, dry_run=dry_run)
        print(f"[组件库] {spec.name}: {result.pypi}")

    _record_port(manifest, state, spec, repo, dirty_files)
    return result


def _record_port(
    manifest: Manifest, state: SyncState, spec: LibSpec, repo: Path, dirty_files: list[str]
) -> None:
    """主仓→组件库方向：本次确实改了库文件，才更新基线。"""
    dirty = set(dirty_files)
    drift = next(
        (item for item in drift_mod.compute_drift(manifest, state) if item.spec.name == spec.name),
        None,
    )
    if drift is None:
        return
    for item in drift.files_with("to_lib", "conflict"):
        if item.mapping.lib not in dirty:
            continue
        state.record_mapping(spec, item.mapping, repo, manifest.project_root)
    state.set_head(spec.name, gitops.head(repo))


def _message(summary: str) -> str:
    text = " ".join((summary or "").split()) or "同步组件库改动"
    return text if len(text) <= MESSAGE_MAX else text[: MESSAGE_MAX - 1] + "…"


class _Abort(RuntimeError):
    """内部中止信号，由 sync_libs 统一转成报告。"""
