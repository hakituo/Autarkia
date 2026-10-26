"""env_sync 的单元测试：.env 键级补缺合并与 CLI 安装兜底。"""

import stat
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sync import env_sync


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8", newline="")
    return path


def _run_merge(local: Path, peer: Path, apply: bool = True) -> int:
    return env_sync.merge(local, peer, apply=apply)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_fill_missing_both_directions(tmp_path):
    local = _write(
        tmp_path / "local.env",
        "# 公共段\nCOMMON_KEY=1\n",
    )
    peer = _write(
        tmp_path / "peer.env",
        "# 公共段\nCOMMON_KEY=1\n"
        "# --- 提交前审查 ---\n"
        "CODERABBIT_API_KEY=secret\n"
        "#CODERABBIT_REVIEW_ENABLED=true\n",
    )
    peer_before = _read(peer)

    assert _run_merge(local, peer) == env_sync.RC_OK

    local_text = _read(local)
    # 对端独有的键（连同注释块）补到本机
    assert "CODERABBIT_API_KEY=secret" in local_text
    assert "# --- 提交前审查 ---" in local_text
    assert "#CODERABBIT_REVIEW_ENABLED=true" in local_text
    # 本机没有对端缺的键 → 对端不变
    assert _read(peer) == peer_before


def test_existing_values_never_overwritten(tmp_path):
    local = _write(tmp_path / "local.env", "MODEL_PATH=F:\\models\\a.gguf\n")
    peer = _write(tmp_path / "peer.env", "MODEL_PATH=/home/user/models/a.gguf\n")
    before = _read(local)

    _run_merge(local, peer)

    assert _read(local) == before


def test_merge_is_idempotent(tmp_path):
    local = _write(tmp_path / "local.env", "A=1\n")
    peer = _write(tmp_path / "peer.env", "A=1\nB=2\n")

    _run_merge(local, peer)
    after_first = _read(local)
    assert _run_merge(local, peer) == env_sync.RC_OK
    assert _read(local) == after_first


def test_dry_run_writes_nothing(tmp_path):
    local = _write(tmp_path / "local.env", "A=1\n")
    peer = _write(tmp_path / "peer.env", "A=1\nB=2\n")
    before = _read(local)

    assert _run_merge(local, peer, apply=False) == env_sync.RC_OK
    assert _read(local) == before


def test_crlf_style_preserved(tmp_path):
    local = _write(tmp_path / "local.env", "A=1\r\n")
    peer = _write(tmp_path / "peer.env", "A=1\nB=2\n")

    _run_merge(local, peer)

    # read_text 会做换行归一化，必须按字节读才能验证 CRLF 原样保留
    text = local.read_bytes().decode("utf-8")
    assert "B=2" in text
    assert text.count("\n") == text.count("\r\n") == 2


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 权限位在 Windows 上不适用")
def test_file_mode_restricted_to_600(tmp_path):
    # .env 含密钥：写回一律收紧到 600，原文件更宽时也不例外
    local = _write(tmp_path / "local.env", "A=1\n")
    local.chmod(0o644)
    peer = _write(tmp_path / "peer.env", "A=1\nB=2\n")

    _run_merge(local, peer)

    assert stat.S_IMODE(local.stat().st_mode) == 0o600
    assert not list(tmp_path.glob("*.sync-tmp"))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 权限位在 Windows 上不适用")
def test_merge_hardens_mode_even_without_changes(tmp_path):
    # 没有键要补时也要收紧既有 .env 的权限：文件里可能有密钥，不能留宽权限
    local = _write(tmp_path / "local.env", "A=1\n")
    local.chmod(0o644)
    peer = _write(tmp_path / "peer.env", "A=1\n")
    peer.chmod(0o644)

    _run_merge(local, peer)

    assert stat.S_IMODE(local.stat().st_mode) == 0o600
    assert stat.S_IMODE(peer.stat().st_mode) == 0o600


def test_non_utf8_peer_skipped(tmp_path, capsys):
    local = _write(tmp_path / "local.env", "A=1\n")
    peer = tmp_path / "peer.env"
    # GB18030 中文常碰巧构成合法 UTF-8，这里直接用确定非法的 0xD6 序列验证检测
    peer.write_bytes(b"KEY=\xd6\xd6\xd6\n")

    assert _run_merge(local, peer) == env_sync.RC_OK
    assert "不是 UTF-8" in capsys.readouterr().out
    assert _read(local) == "A=1\n"


def test_same_path_skipped(tmp_path):
    path = _write(tmp_path / "same.env", "A=1\n")

    assert _run_merge(path, path) == env_sync.RC_OK


def test_ensure_cli_reports_installed_version(monkeypatch, capsys):
    # ensure_cli 在 cli_setup 模块内查 cli_installed / subprocess，必须 patch 到实现处
    monkeypatch.setattr(env_sync.cli_setup, "cli_installed", lambda: "/usr/bin/coderabbit")
    monkeypatch.setattr(
        env_sync.cli_setup.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout="1.2.3", stderr=""),
    )

    assert env_sync.ensure_cli() == env_sync.RC_OK
    assert "已就位" in capsys.readouterr().out


def test_cli_installed_falls_back_to_local_bin(tmp_path, monkeypatch):
    # install.sh 装到 ~/.local/bin，但当前进程 PATH 未必包含它：必须能兜底检出。
    # Windows Python 的 Path.home() 不看 HOME 环境变量，直接 patch Path.home 才跨平台
    cli = tmp_path / ".local" / "bin" / "coderabbit"
    cli.parent.mkdir(parents=True)
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    cli.chmod(0o700)
    monkeypatch.setattr(env_sync.cli_setup.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(env_sync.cli_setup.shutil, "which", lambda name: None)

    assert env_sync.cli_installed() == str(cli)


def test_install_cli_direct_success_no_proxy_retry(monkeypatch):
    for var in ("https_proxy", "http_proxy"):
        monkeypatch.delenv(var, raising=False)
    calls: list[dict] = []

    def fake_runner(cmd, env=None, **kw):
        calls.append({"env": dict(env)})
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    assert env_sync.install_cli(
        runner=fake_runner, finder=lambda: "/usr/bin/coderabbit"
    )
    assert len(calls) == 1
    assert "https_proxy" not in calls[0]["env"]


def test_install_cli_falls_back_to_proxy(monkeypatch):
    for var in ("https_proxy", "http_proxy"):
        monkeypatch.delenv(var, raising=False)
    calls: list[dict] = []

    def fake_runner(cmd, env=None, **kw):
        calls.append({"env": dict(env)})
        if len(calls) == 1:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="连接被重置")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    assert env_sync.install_cli(
        runner=fake_runner, finder=lambda: "/usr/bin/coderabbit"
    )
    assert len(calls) == 2
    assert calls[1]["env"]["https_proxy"] == env_sync.DEFAULT_PROXY


def test_install_cli_timeout_falls_back_to_proxy(monkeypatch):
    for var in ("https_proxy", "http_proxy"):
        monkeypatch.delenv(var, raising=False)
    calls: list[dict] = []

    def fake_runner(cmd, env=None, **kw):
        calls.append({"env": dict(env)})
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(cmd, env_sync.INSTALL_TIMEOUT_S)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    assert env_sync.install_cli(
        runner=fake_runner, finder=lambda: "/usr/bin/coderabbit"
    )
    assert len(calls) == 2
    assert calls[1]["env"]["https_proxy"] == env_sync.DEFAULT_PROXY


def test_install_cli_all_attempts_fail(monkeypatch, capsys):
    def fake_runner(cmd, env=None, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    assert not env_sync.install_cli(runner=fake_runner, finder=lambda: None)
    assert "boom" in capsys.readouterr().out


def test_main_toggle_disabled(monkeypatch):
    monkeypatch.setenv(env_sync.ENV_TOGGLE, "0")

    assert env_sync.main(["merge", "--auto"]) == env_sync.RC_OK


def test_main_merge_auto_without_peer(tmp_path, monkeypatch):
    monkeypatch.delenv(env_sync.ENV_TOGGLE, raising=False)
    local = _write(tmp_path / ".env", "A=1\n")

    rc = env_sync.main(
        ["merge", "--local", str(local), "--peer-root", str(tmp_path / "nope"), "--auto"]
    )

    assert rc == env_sync.RC_OK
