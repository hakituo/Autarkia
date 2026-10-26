"""验证组件库双向同步（映射、基线、漂移判定、磁盘镜像、自动提交接入）。

运行：venv_cpu/bin/python tests/scripts/sync/verify_libs_sync.py

只读真实仓库的元数据；需要写操作的用例全部在临时目录里建假仓库。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sync.libs.autoport import port_additions
from scripts.sync.libs.drift import compute_drift
from scripts.sync.libs.gitops import head, mirror
from scripts.sync.libs.manifest import LibSpec, Manifest, Mapping, load_manifest
from scripts.sync.libs.state import SyncState, file_hash

UNPUBLISHED = {
    "Autarkia-Concurrency",
    "Autarkia-Emotion",
    "Autarkia-Personas",
    "Autarkia-Vocab",
}


def check_manifest() -> list[str]:
    manifest = load_manifest()
    errors: list[str] = []
    if len(manifest.libs) != 9:
        errors.append(f"组件库数量应为 9，实际 {len(manifest.libs)}")
    total = 0
    for spec in manifest.libs:
        repo = manifest.repo(spec)
        if not (repo / ".git").is_dir():
            errors.append(f"{spec.name}: 仓库不存在 {repo}")
        if spec.published != (spec.name not in UNPUBLISHED):
            errors.append(f"{spec.name}: published 标记与未发布清单不一致")
        want_parent = "unpublished" if spec.name in UNPUBLISHED else ""
        if Path(spec.path).parent.as_posix() != (want_parent or "."):
            errors.append(f"{spec.name}: 目录层级应为 {want_parent or '根目录'}，实际 {spec.path}")
        seen: set[str] = set()
        for mapping in spec.mappings:
            total += 1
            if mapping.lib in seen:
                errors.append(f"{spec.name}: 组件库文件重复映射 {mapping.lib}")
            seen.add(mapping.lib)
            if not (repo / mapping.lib).is_file():
                errors.append(f"{spec.name}: 缺少库文件 {mapping.lib}")
            for source in mapping.main:
                if not (manifest.project_root / source).is_file():
                    errors.append(f"{spec.name}: 缺少主仓源文件 {source}")
    if total != 51:
        errors.append(f"映射总数应为 51，实际 {total}")
    return errors


def check_remotes() -> list[str]:
    manifest = load_manifest()
    errors: list[str] = []
    for spec in manifest.libs:
        repo = manifest.repo(spec)
        proc = subprocess.run(
            ["git", "-c", f"safe.directory={repo}", "remote", "get-url", "origin"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        has_origin = proc.returncode == 0 and bool(proc.stdout.strip())
        if spec.published and not has_origin:
            errors.append(f"{spec.name}: 已发布但缺少 origin")
        if not spec.published and has_origin:
            errors.append(f"{spec.name}: 未发布却配置了 origin（清单需更新）")
    return errors


def check_state() -> list[str]:
    manifest = load_manifest()
    state = SyncState(manifest.state_dir).load()
    errors: list[str] = []
    if not state.path.exists():
        return [f"基线不存在：{state.path}（先跑 libs_sync.py baseline）"]
    total = sum(len(spec.mappings) for spec in manifest.libs)
    recorded = sum(len(files) for files in state.data.get("files", {}).values())
    if recorded != total:
        errors.append(f"基线条目 {recorded} != 映射总数 {total}")
    for spec in manifest.libs:
        for mapping in spec.mappings:
            if state.get(spec.name, mapping.lib) is None:
                errors.append(f"{spec.name}: 缺少基线 {mapping.lib}")
            if not state.base_lib_path(spec.name, mapping.lib).exists():
                errors.append(f"{spec.name}: 缺少库基线快照 {mapping.lib}")
            for source in mapping.main:
                if not state.base_main_path(spec.name, source).exists():
                    errors.append(f"{spec.name}: 缺少主仓基线快照 {source}")
    return errors


def check_hash_eol() -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        lf = Path(tmp) / "lf.py"
        crlf = Path(tmp) / "crlf.py"
        lf.write_bytes(b"a = 1\nb = 2\n")
        crlf.write_bytes(b"a = 1\r\nb = 2\r\n")
        if file_hash(lf) != file_hash(crlf):
            return ["CRLF/LF 未归一化：双系统基线会误判"]
    return []


def test_drift_flags() -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        main_file = root / "core" / "a.py"
        lib_file = root / "libs" / "L" / "src" / "m.py"
        main_file.parent.mkdir(parents=True)
        lib_file.parent.mkdir(parents=True)
        main_file.write_text("value = 1\n", encoding="utf-8")
        lib_file.write_text("VALUE = 1\n", encoding="utf-8")
        spec = LibSpec(
            name="L",
            path="L",
            published=False,
            pypi=False,
            mappings=(Mapping(lib="src/m.py", main=("core/a.py",)),),
        )
        manifest = Manifest(
            libs=(spec,),
            project_root=root,
            libs_root=root / "libs",
            peer_root=None,
            state_dir=root / "state",
        )
        state = SyncState(manifest.state_dir).load()
        state.record_all(manifest, lib_file.parents[1], spec)

        def flag() -> str:
            return compute_drift(manifest, state)[0].files[0].flag

        if flag() != "in_sync":
            return [f"基线后状态应为 in_sync，实际 {flag()}"]
        main_file.write_text("value = 2\n", encoding="utf-8")
        if flag() != "to_lib":
            return [f"只改主仓应为 to_lib，实际 {flag()}"]
        lib_file.write_text("VALUE = 2\n", encoding="utf-8")
        if flag() != "conflict":
            return [f"两侧都改应为 conflict，实际 {flag()}"]
        main_file.write_text("value = 1\n", encoding="utf-8")
        if flag() != "to_main":
            return [f"只改组件库应为 to_main，实际 {flag()}"]
    return []


def test_autoport() -> list[str]:
    base = "import json\n\n\ndef old():\n    return 1\n"
    source = (
        base
        + "\n\ndef is_array(text):\n"
        + "    try:\n"
        + "        return isinstance(json.loads(text), list)\n"
        + "    except ValueError:\n"
        + "        return False\n"
    )
    target = "import json\n\n\ndef old():\n    return 1\n"
    result = port_additions(base, source, target)
    if result.added != ["is_array"] or "def is_array" not in result.text:
        return [f"纯新增符号应可移植，实际 added={result.added} reason={result.reason}"]

    modified = source.replace("return 1", "return 2")
    result = port_additions(base, modified, target)
    if not result.reason.startswith("修改了已有符号") or result.added:
        return [f"修改已有符号应拒绝，实际 {result.reason}"]

    missing = source.replace("json.loads(text)", "json.loads(_missing_name(text))")
    result = port_additions(base, missing, target)
    if "依赖目标缺失" not in result.reason or result.added:
        return [f"依赖缺失应拒绝，实际 {result.reason}"]

    occupied = target + "\n\ndef is_array(text):\n    return []\n"
    result = port_additions(base, source, occupied)
    if not result.reason.startswith("目标已存在同名符号") or result.added:
        return [f"目标已有同名符号应拒绝，实际 {result.reason}"]
    return []


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "verify")
    _git(repo, "config", "user.email", "verify@example.invalid")


def test_mirror() -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        left, right = root / "left", root / "right"
        _init_repo(left)
        (left / "a.txt").write_text("one\n", encoding="utf-8")
        _git(left, "add", "-A")
        _git(left, "commit", "-m", "init")
        _git(root, "clone", str(left), str(right))
        _git(right, "config", "user.name", "verify")
        _git(right, "config", "user.email", "verify@example.invalid")

        (left / "a.txt").write_text("two\n", encoding="utf-8")
        _git(left, "add", "-A")
        _git(left, "commit", "-m", "left ahead")
        pushed = mirror(left, right)
        if pushed.status != "pushed" or head(left) != head(right):
            return [f"左→右镜像失败: {pushed.status} {pushed.detail}"]

        (right / "b.txt").write_text("right\n", encoding="utf-8")
        _git(right, "add", "-A")
        _git(right, "commit", "-m", "right ahead")
        pulled = mirror(left, right)
        if pulled.status != "pulled" or head(left) != head(right):
            return [f"右→左镜像失败: {pulled.status} {pulled.detail}"]
    return []


def check_wiring() -> list[str]:
    errors: list[str] = []
    helper = PROJECT_ROOT / "scripts" / "git" / "auto_commit_push.py"
    bridge = PROJECT_ROOT / "scripts" / "git" / "auto_commit" / "libs_bridge.py"
    text = helper.read_text(encoding="utf-8")
    bridge_text = bridge.read_text(encoding="utf-8")
    for flag in ("--no-libs", "--strict-libs", "--libs-pypi"):
        if flag not in bridge_text:
            errors.append(f"libs_bridge.py 缺少参数 {flag}")
    if "sync_related_libs" not in bridge_text:
        errors.append("libs_bridge.py 未实现 sync_related_libs")
    if "run_libs_phase" not in text:
        errors.append("auto_commit_push.py 未调用 run_libs_phase")
    start = (PROJECT_ROOT / "start.sh").read_text(encoding="utf-8")
    if "libs_sync.py mirror" not in start:
        errors.append("start.sh 未接入组件库镜像")
    daily = (PROJECT_ROOT / "scripts" / "daily" / "daily.py").read_text(encoding="utf-8")
    if "libs_sync.py" not in daily:
        errors.append("daily.py 未接入 libs 子命令")
    return errors


def main() -> int:
    checks = [
        ("映射清单完整", check_manifest),
        ("发布标记与远端", check_remotes),
        ("同步基线完整", check_state),
        ("换行符归一化", check_hash_eol),
        ("漂移方向判定", test_drift_flags),
        ("纯新增符号移植", test_autoport),
        ("双系统镜像", test_mirror),
        ("自动提交接入", check_wiring),
    ]
    failed = False
    for name, func in checks:
        try:
            errors = func()
        except Exception as exc:  # noqa: BLE001 - 验证脚本需报告任何异常
            errors = [f"检查执行异常: {type(exc).__name__}: {exc}"]
        print(f"[{'PASS' if not errors else 'FAIL'}] {name}")
        for error in errors:
            print(f"  - {error}")
            failed = True
    if failed:
        print("\n验证失败：组件库同步存在未就绪项")
        return 1
    print("\n验证通过：映射、基线、漂移判定、镜像与自动提交接入均正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
