r"""验证提交前 CodeRabbit 审查门禁。

覆盖：NDJSON 解析、提交范围过滤、严重度拆分、累积文件去重、代码文件判定、
配置读取、外部故障放行/拦截。不联网、不调用真实 CodeRabbit CLI。

运行：
    venv_cpu\Scripts\python.exe -m tests.scripts.git.verify_coderabbit_gate
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

_FAILED: list[str] = []
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.git.auto_commit.review_gate import (  # noqa: E402
    Finding,
    append_backlog,
    filter_findings,
    load_config,
    parse_findings,
    run_review_gate,
    should_review,
    split_findings,
)

NDJSON = "\n".join(
    [
        '{"type":"review_context","currentBranch":"main"}',
        '{"type":"finding","severity":"major","fileName":"scripts/a.py",'
        '"startLine":12,"title":"未处理的空值","comment":"先判空"}',
        '{"type":"finding","severity":"minor","fileName":"scripts/b.py",'
        '"startLine":3,"title":"命名不一致","comment":"统一为 snake_case"}',
        '{"type":"finding","severity":"minor","fileName":"scripts/other.py",'
        '"startLine":5,"title":"范围外"}',
        '{"type":"complete","status":"review_completed"}',
    ]
)


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    _FAILED.append(msg)


def _write_env(path: Path, extra: str = "") -> Path:
    path.write_text(
        "CODERABBIT_API_KEY=cr-test\n"
        "CODERABBIT_CLI_PATH=cr-fake\n"
        f"{extra}",
        encoding="utf-8",
    )
    return path


def _runner(code: int, out: str, err: str = "", calls: list | None = None):
    def _run(cmd, cwd=None, timeout=30, env=None):
        if calls is not None:
            calls.append(list(cmd))
        return code, out, err

    return _run


def test_parse_filter_split() -> None:
    print("\n=== 测试 1: NDJSON 解析 / 范围过滤 / 严重度拆分 ===")
    findings, errors = parse_findings(NDJSON.splitlines())
    scoped = filter_findings(findings, ["scripts/a.py", "scripts/b.py"])
    blocking, backlog = split_findings(scoped, frozenset({"critical", "major"}))
    if len(findings) == 3 and not errors:
        _ok("解析出 3 条 finding，error 事件为空")
    else:
        _fail(f"解析结果异常: findings={len(findings)} errors={errors}")
    if [item.file_name for item in scoped] == ["scripts/a.py", "scripts/b.py"]:
        _ok("范围外的 scripts/other.py 被过滤")
    else:
        _fail("范围过滤不正确")
    if len(blocking) == 1 and len(backlog) == 1:
        _ok("major 进阻断，minor 进普通提示")
    else:
        _fail("严重度拆分不正确")


def test_backlog_dedup() -> None:
    print("\n=== 测试 2: 累积文件去重 ===")
    finding = Finding("minor", "scripts/b.py", 3, "命名不一致", "统一为 snake_case")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "review_backlog" / "coderabbit_findings.md"
        first = append_backlog(path, [finding], "2026-10-25 10:00:00")
        second = append_backlog(path, [finding], "2026-10-25 11:00:00")
        content = path.read_text(encoding="utf-8")
    if first == 1 and second == 0:
        _ok("首次写入 1 条，重复运行不新增")
    else:
        _fail(f"去重异常: first={first} second={second}")
    if content.count("命名不一致") == 1:
        _ok("文件里只有一条同名记录")
    else:
        _fail("累积文件出现重复条目")


def test_should_review() -> None:
    print("\n=== 测试 3: 代码文件判定 ===")
    if not should_review(["docs/updates/2026/10/2026-10-25.md", ".trae/memory/MEMORY.md"]):
        _ok("纯文档提交跳过审查")
    else:
        _fail("纯文档被判定为需要审查")
    if should_review(["docs/a.md", "scripts/git/x.py"]):
        _ok("含 .py 的提交需要审查")
    else:
        _fail("含代码文件的提交未被识别")
    if should_review(["clients/frontend/aveline-android/android/App.kt"]):
        _ok("Android .kt 需要审查")
    else:
        _fail("Android 代码未被识别")


def test_config() -> None:
    print("\n=== 测试 4: 配置读取与下限 ===")
    with tempfile.TemporaryDirectory() as tmp:
        env_path = _write_env(Path(tmp) / ".env", "CODERABBIT_REVIEW_TIMEOUT=30\n")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CODERABBIT_REVIEW_TIMEOUT", None)
            config = load_config(env_path)
    if config.api_key == "cr-test" and config.cli_path == "cr-fake":
        _ok("API Key 与 CLI 路径读取正确")
    else:
        _fail("基础配置读取不正确")
    if config.timeout == 60:
        _ok("超时下限被钳制到 60 秒")
    else:
        _fail(f"超时下限未生效: {config.timeout}")
    if config.block_severities == frozenset({"critical", "major"}) and not config.fail_closed:
        _ok("默认阻断 severity 与 fail_closed 正确")
    else:
        _fail("默认阻断策略不正确")
    with tempfile.TemporaryDirectory() as tmp:
        env_path = _write_env(Path(tmp) / ".env", "CODERABBIT_REVIEW_FAIL_CLOSED=true\n")
        with patch.dict(os.environ, {"CODERABBIT_REVIEW_TIMEOUT": "120"}, clear=False):
            config = load_config(env_path)
    if config.fail_closed and config.timeout == 120:
        _ok("fail_closed 与进程环境变量覆盖生效")
    else:
        _fail("覆盖配置未生效")


def test_gate_blocking() -> None:
    print("\n=== 测试 5: 阻断级 finding 拦下提交 ===")
    with tempfile.TemporaryDirectory() as tmp:
        env_path = _write_env(Path(tmp) / ".env")
        calls: list = []
        code = run_review_gate(
            ["scripts/a.py"],
            command_runner=_runner(0, NDJSON, calls=calls),
            env_path=env_path,
            now_str="2026-10-25 10:00:00",
        )
    if code == 6:
        _ok("major 触发拦截（返回 6）")
    else:
        _fail(f"未拦截 major: code={code}")
    if calls and "--uncommitted" in calls[0] and "--api-key" in calls[0]:
        _ok("调用参数包含 --uncommitted 与 --api-key")
    else:
        _fail("CLI 调用参数不正确")


def test_gate_backlog_and_infra() -> None:
    print("\n=== 测试 6: 普通提示累积 / 外部故障策略 ===")
    minor_only = "\n".join(
        [
            '{"type":"finding","severity":"minor","fileName":"scripts/b.py",'
            '"startLine":3,"title":"命名不一致"}',
            '{"type":"complete","status":"review_completed"}',
        ]
    )
    with tempfile.TemporaryDirectory() as tmp:
        backlog = Path(tmp) / "backlog.md"
        env_path = _write_env(
            Path(tmp) / ".env", f"CODERABBIT_BACKLOG_PATH={backlog}\n"
        )
        code = run_review_gate(
            ["scripts/b.py"],
            command_runner=_runner(0, minor_only),
            env_path=env_path,
            now_str="2026-10-25 10:00:00",
        )
        recorded = backlog.is_file() and "命名不一致" in backlog.read_text(encoding="utf-8")
    if code == 0 and recorded:
        _ok("minor 不拦提交，并写入累积文件")
    else:
        _fail(f"普通提示处理异常: code={code} recorded={recorded}")

    with tempfile.TemporaryDirectory() as tmp:
        env_path = _write_env(Path(tmp) / ".env")
        relaxed = run_review_gate(
            ["scripts/a.py"],
            command_runner=_runner(1, "", "network unreachable"),
            env_path=env_path,
        )
        env_path = _write_env(
            Path(tmp) / ".env", "CODERABBIT_REVIEW_FAIL_CLOSED=true\n"
        )
        strict = run_review_gate(
            ["scripts/a.py"],
            command_runner=_runner(1, "", "network unreachable"),
            env_path=env_path,
        )
    if relaxed == 0 and strict == 6:
        _ok("外部故障默认放行，fail_closed=true 时拦截")
    else:
        _fail(f"外部故障策略异常: relaxed={relaxed} strict={strict}")


def test_gate_skips() -> None:
    print("\n=== 测试 7: 关闭开关 / 纯文档提交不调用 CLI ===")
    with tempfile.TemporaryDirectory() as tmp:
        env_path = _write_env(Path(tmp) / ".env", "CODERABBIT_REVIEW_ENABLED=false\n")
        calls: list = []
        disabled = run_review_gate(
            ["scripts/a.py"],
            command_runner=_runner(0, NDJSON, calls=calls),
            env_path=env_path,
        )
    if disabled == 0 and not calls:
        _ok("开关关闭时直接放行且不调用 CLI")
    else:
        _fail("关闭开关后仍调用了 CLI")
    with tempfile.TemporaryDirectory() as tmp:
        env_path = _write_env(Path(tmp) / ".env")
        calls = []
        doc_only = run_review_gate(
            ["docs/updates/2026/10/2026-10-25.md"],
            command_runner=_runner(0, NDJSON, calls=calls),
            env_path=env_path,
        )
    if doc_only == 0 and not calls:
        _ok("纯文档提交直接放行且不调用 CLI")
    else:
        _fail("纯文档提交仍调用了 CLI")


def main() -> int:
    print("=" * 64)
    print("CodeRabbit 提交前审查门禁验证")
    print("=" * 64)
    test_parse_filter_split()
    test_backlog_dedup()
    test_should_review()
    test_config()
    test_gate_blocking()
    test_gate_backlog_and_infra()
    test_gate_skips()
    print("=" * 64)
    if _FAILED:
        print(f"失败 {len(_FAILED)} 项：" + "、".join(_FAILED))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
