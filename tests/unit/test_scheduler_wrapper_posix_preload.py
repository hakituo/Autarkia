#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scheduler_wrapper 的 Linux 共享库预加载单测。

背景：CMake 把编译时的绝对路径写进 RUNPATH，项目目录搬迁后 RUNPATH 失效，
scheduler_py 的 DT_NEEDED（libllama.so.0）找不到。加载器现在在导入前用
RTLD_GLOBAL 预加载扩展同级 bin/ 下的 .so。

本文件不依赖真实编译产物：ctypes.CDLL 全部替换为假实现。
"""

from __future__ import annotations

import ctypes
import importlib.machinery
import os
import sys

import pytest

from core.services.scheduler import scheduler_wrapper as sw


def _write_libs(directory):
    """造一个含共享库、扩展本体与普通文件的 bin/ 目录。"""
    bin_dir = directory / "bin"
    bin_dir.mkdir()
    (bin_dir / "libllama.so.0").write_bytes(b"\x7fELF")
    (bin_dir / "libggml-base.so.0").write_text("")
    (bin_dir / "scheduler_py.cpython-313-x86_64-linux-gnu.so").write_text("")
    (bin_dir / "notes.txt").write_text("")
    return bin_dir


def test_preload_only_loads_extension_libs(tmp_path, monkeypatch):
    """只加载 .so，跳过扩展本体与非共享库文件，且统一用 RTLD_GLOBAL。"""
    _write_libs(tmp_path)
    calls = []
    monkeypatch.setattr(sw, "_POSIX_LIB_HANDLES", [])

    def _fake_cdll(path, mode=None):
        calls.append((os.path.basename(path), mode))
        return object()

    monkeypatch.setattr(ctypes, "CDLL", _fake_cdll)

    sw._preload_posix_shared_libs(str(tmp_path))

    names = [name for name, _ in calls]
    assert "libllama.so.0" in names
    assert "libggml-base.so.0" in names
    assert "notes.txt" not in names
    assert "scheduler_py.cpython-313-x86_64-linux-gnu.so" not in names
    assert all(mode == ctypes.RTLD_GLOBAL for _, mode in calls)


def test_preload_retries_failed_libs_and_swallows_oserror(tmp_path, monkeypatch):
    """库间依赖顺序导致的首次失败会在第二遍重试，且异常不向外抛。"""
    _write_libs(tmp_path)
    calls = []
    monkeypatch.setattr(sw, "_POSIX_LIB_HANDLES", [])

    def _fake_cdll(path, mode=None):
        calls.append(os.path.basename(path))
        if path.endswith("libggml-base.so.0"):
            raise OSError("Missing dependency")
        return object()

    monkeypatch.setattr(ctypes, "CDLL", _fake_cdll)

    sw._preload_posix_shared_libs(str(tmp_path))

    assert calls.count("libggml-base.so.0") == 2


def test_preload_deduplicates_symlinks(tmp_path, monkeypatch):
    """指向同一真实文件的软链接只加载一次。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    target = bin_dir / "libllama.so.0.0.0"
    target.write_text("")
    try:
        (bin_dir / "libllama.so.0").symlink_to(target.name)
    except OSError:
        pytest.skip("当前平台不支持软链接")

    calls = []
    monkeypatch.setattr(sw, "_POSIX_LIB_HANDLES", [])
    monkeypatch.setattr(
        ctypes, "CDLL", lambda path, mode=None: calls.append(path) or object()
    )

    sw._preload_posix_shared_libs(str(tmp_path))

    assert len(calls) == 1


def test_import_scheduler_py_preloads_before_import(tmp_path, monkeypatch):
    """找到 ABI 兼容候选时，导入前会预加载该目录的配套共享库。"""
    build_dir = tmp_path / "cpp_modules" / "cpp_scheduler" / "build"
    build_dir.mkdir(parents=True)
    suffix = importlib.machinery.EXTENSION_SUFFIXES[0]
    (build_dir / f"scheduler_py{suffix}").write_text("")

    fake_file = tmp_path / "core" / "services" / "scheduler" / "scheduler_wrapper.py"
    monkeypatch.setattr(sw, "__file__", str(fake_file))
    calls = []
    monkeypatch.setattr(sw, "_preload_posix_shared_libs", calls.append)
    monkeypatch.setattr(sw, "_DLL_DIR_HANDLES", [])

    sys.path.insert(0, str(build_dir))
    try:
        assert sw._import_scheduler_py() is None
    finally:
        sys.path.remove(str(build_dir))
        sys.modules.pop("scheduler_py", None)

    assert calls == [str(build_dir)]
