#!/usr/bin/env python3
""".env 键级并集合并：解析、补缺写入与三向报告。

本模块只关心 ``.env`` 文件本身，不知道对端在哪、也不负责装 CLI（见
``cli_setup``）；入口编排与命令行解析在包的 ``__init__`` 门面里。
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

#: 活跃键（非注释）行：``KEY=VALUE``，键名与 dotenv 惯例一致
_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

RC_OK = 0
RC_ERROR = 1


class EnvFile:
    """一个 ``.env`` 文件的解析结果：键 →（前置注释块, 原始行, 尾随注释块）。

    注释行的归属规则：挂到它之后**下一个**活跃键（段头、说明都算下一键的前置
    注释）；文件末尾再没有键的挂到**上一个**键（如 ``#CODERABBIT_REVIEW_ENABLED``
    这类跟在键后面的注释示例行）。补缺时前置 + 键行 + 尾随一起搬运，保住
    「第 9 段 CodeRabbit」这类分段说明与注释掉的可选项。带 ``#`` 前缀的示例键
    不算活跃键，只作为注释文本搬运。
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        raw = path.read_bytes()
        self.has_bom = raw.startswith(b"\xef\xbb\xbf")
        self.text = raw.decode("utf-8-sig")
        self.eol = "\r\n" if "\r\n" in self.text else "\n"
        lines = self.text.splitlines()
        key_at = [i for i, line in enumerate(lines) if _KEY_RE.match(line)]
        next_key: dict[int, int] = {}
        for pos, idx in enumerate(key_at):
            start = 0 if pos == 0 else key_at[pos - 1] + 1
            for i in range(start, idx + 1):
                next_key[i] = idx
        self.entries: dict[str, tuple[list[str], str, list[str]]] = {
            lines[idx].split("=", 1)[0]: ([], lines[idx], []) for idx in key_at
        }
        for i, line in enumerate(lines):
            if _KEY_RE.match(line):
                continue
            owner = next_key.get(i)
            if owner is None:
                owner = key_at[-1] if key_at and i > key_at[-1] else None
            if owner is None:
                continue  # 空文件开头的游离注释：两侧都没有键可挂，丢弃
            key = lines[owner].split("=", 1)[0]
            slot = self.entries[key]
            if i < owner:
                slot[0].append(line)
            else:
                slot[2].append(line)


def read_env(path: Path) -> EnvFile | None:
    """读取并解析 ``.env``；文件缺失、非 UTF-8、不是常规文件时返回 None。"""
    if not path.is_file():
        return None
    try:
        return EnvFile(path)
    except UnicodeDecodeError:
        print(f"[WARN] {path} 不是 UTF-8，跳过（不猜测编码，避免写坏）")
        return None


def atomic_write(path: Path, text: str, has_bom: bool) -> None:
    """按原文件风格原子写回，权限一律收紧到 600。

    ``.env`` 含 API key：临时文件用 :func:`tempfile.mkstemp` 在同目录生成——
    文件名不可预测（防符号链接/抢占竞争）、创建即 0600、不经过默认 umask 的
    宽权限窗口；写完原子替换，失败时清理临时文件。ntfs-3g 等不支持 POSIX
    权限的挂载上 0600 尽力而为。
    """
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".sync-tmp", dir=path.parent
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            if has_bom:
                fh.write("\ufeff")
            fh.write(text)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass  # ntfs-3g 等挂载不支持 POSIX 权限，保持挂载默认即可
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def append_entries(
    target: EnvFile, incoming: dict[str, tuple[list[str], str, list[str]]]
) -> bool:
    """把 ``incoming`` 里目标缺的键追加到文件末尾，返回是否有改动。

    追加内容统一成目标文件的换行风格；原文件不以换行结尾时先补一个，避免新键
    粘在最后一行键值后面。
    """
    missing = {k: v for k, v in incoming.items() if k not in target.entries}
    if not missing:
        return False
    text = target.text
    if text and not text.endswith("\n"):
        text += target.eol
    for key in sorted(missing):
        comments, line, trailing = missing[key]
        for comment in comments:
            text += comment.rstrip("\r\n") + target.eol
        text += line.rstrip("\r\n") + target.eol
        for comment in trailing:
            text += comment.rstrip("\r\n") + target.eol
        print(f"[INFO] 补缺 {target.path.name}：{key}")
    atomic_write(target.path, text, target.has_bom)
    target.entries.update(missing)
    return True


def harden_mode(path: Path) -> None:
    """把 ``.env`` 权限收紧到 0600；ntfs-3g 等挂载不支持时尽力而为。"""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def merge(local_path: Path, peer_path: Path, apply: bool) -> int:
    """键级并集合并：双向补缺，不覆盖已有值；值不同的键只报告。"""
    local = read_env(local_path)
    peer = read_env(peer_path)
    if local is None or peer is None:
        print(
            f"[INFO] 缺少可合并的 .env（local={local_path.exists()} "
            f"peer={peer_path.exists()}），跳过"
        )
        return RC_OK
    if local_path.resolve() == peer_path.resolve():
        print("[INFO] 对端 .env 与本机是同一个文件，跳过")
        return RC_OK

    differing = sorted(
        key
        for key in local.entries.keys() & peer.entries.keys()
        if local.entries[key][1].split("=", 1)[1].rstrip("\r")
        != peer.entries[key][1].split("=", 1)[1].rstrip("\r")
    )
    for key in differing:
        print(f"[INFO] 两边都有且值不同，保持本机现状：{key}")

    if not apply:
        would_local = sorted(k for k in peer.entries if k not in local.entries)
        would_peer = sorted(k for k in local.entries if k not in peer.entries)
        if would_local or would_peer:
            print(f"[INFO] dry-run：将补到本机 {would_local or '无'}")
            print(f"[INFO] dry-run：将补到对端 {would_peer or '无'}")
        else:
            print("[INFO] dry-run：两边键集合已一致，无需合并")
        return RC_OK

    changed = append_entries(local, peer.entries)
    changed = append_entries(peer, local.entries) or changed
    # 无论有没有键要补，都把两边既有 .env 收紧到 0600（可能含密钥，不能留宽权限）
    harden_mode(local_path)
    harden_mode(peer_path)
    print(f"[PASS] .env 合并完成（{'有改动' if changed else '两边键集合已一致'}；"
          f"值不同保持现状 {len(differing)} 项）")
    return RC_OK
