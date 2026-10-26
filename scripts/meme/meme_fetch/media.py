"""图片落盘层：内容哈希去重、尺寸/体积规整、原子写入。

去重按「文件内容 md5」而不是路径，所以同一张图从不同源重复抓到也只会留一份。
GIF 不重编码（Pillow 重存会丢动画），超限直接跳过并计入统计。
"""

from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass
from pathlib import Path

from core.utils.logger import get_logger

from .config import NormalizePolicy

logger = get_logger("meme_fetch_media")

#: 需要重编码的静态图扩展名（GIF 单独处理）
_STATIC_EXTS = (".jpg", ".jpeg", ".png", ".webp")
#: 批量保存时的临时后缀（与备份脚本保持一致，便于识别残留）
_TMP_SUFFIX = ".fetch-tmp"


@dataclass
class WriteStats:
    """一次落盘的累计统计。"""

    written: int = 0
    duplicates: int = 0
    skipped_small: int = 0
    skipped_oversize: int = 0
    failed: int = 0
    bytes_written: int = 0

    def merge(self, other: WriteStats) -> None:
        self.written += other.written
        self.duplicates += other.duplicates
        self.skipped_small += other.skipped_small
        self.skipped_oversize += other.skipped_oversize
        self.failed += other.failed
        self.bytes_written += other.bytes_written


def content_hash(data: bytes) -> str:
    """返回字节内容 md5（去重键）。"""
    return hashlib.md5(data).hexdigest()


def _save_static(data: bytes, dst: Path, policy: NormalizePolicy) -> int | None:
    """把静态图规整后写入 dst，返回写入字节数；失败返回 None。"""
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:  # noqa: BLE001 - 打不开的就是坏图，跳过即可
        return None

    width, height = image.size
    if min(width, height) < policy.min_side:
        return None

    suffix = dst.suffix.lower()
    needs_resize = max(width, height) > policy.max_side
    needs_reencode = needs_resize or len(data) > policy.max_bytes
    if not needs_reencode:
        payload = data
    else:
        if needs_resize:
            image.thumbnail((policy.max_side, policy.max_side))
        # 有透明通道的保持 RGBA，其余转 RGB（避免 PNG 存成调色板被某些客户端显示异常）
        if suffix in (".jpg", ".jpeg"):
            payload = _encode_image(image.convert("RGB"), "JPEG")
        elif suffix == ".webp":
            payload = _encode_image(image.convert("RGBA"), "WEBP")
        else:
            has_alpha = image.mode in ("RGBA", "LA", "P") or "transparency" in image.info
            payload = _encode_image(image.convert("RGBA") if has_alpha else image.convert("RGB"),
                                    "PNG")
        if payload is None:
            return None

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + _TMP_SUFFIX)
    try:
        tmp.write_bytes(payload)
        os.replace(tmp, dst)
    except OSError as exc:
        logger.warning(f"写入失败 {dst}: {exc}")
        tmp.unlink(missing_ok=True)
        return None
    return len(payload)


def _encode_image(image, fmt: str) -> bytes | None:
    """按格式编码到内存；失败返回 None。"""
    buffer = io.BytesIO()
    try:
        if fmt == "PNG":
            image.save(buffer, "PNG", optimize=True)
        elif fmt == "JPEG":
            image.save(buffer, "JPEG", quality=88, optimize=True)
        elif fmt == "WEBP":
            image.save(buffer, "WEBP", quality=88)
        else:
            return None
    except Exception:  # noqa: BLE001 - GIF 等不支持的模式直接放弃这张
        return None
    return buffer.getvalue()


def store_bytes(
    data: bytes,
    dst: Path,
    policy: NormalizePolicy,
    stats: WriteStats,
) -> bool:
    """规整并写入一张图片；返回是否真的写入了文件。"""
    if len(data) < policy.min_bytes:
        stats.skipped_small += 1
        return False

    suffix = dst.suffix.lower()
    if suffix == ".gif":
        # GIF 保留原字节以保住动画；超限则整张放弃
        if len(data) > policy.gif_max_bytes:
            stats.skipped_oversize += 1
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + _TMP_SUFFIX)
        try:
            tmp.write_bytes(data)
            os.replace(tmp, dst)
        except OSError as exc:
            logger.warning(f"写入失败 {dst}: {exc}")
            tmp.unlink(missing_ok=True)
            stats.failed += 1
            return False
        stats.written += 1
        stats.bytes_written += len(data)
        return True

    written = _save_static(data, dst, policy)
    if written is None:
        stats.failed += 1
        return False
    stats.written += 1
    stats.bytes_written += written
    return True


def safe_name(raw: str, fallback: str = "meme") -> str:
    """把源文件名规整成可落盘的名字（去掉路径分隔符与 Windows 保留字符）。"""
    name = Path(str(raw or "")).name
    for token in ("\\", "/", ":", "*", "?", '"', "<", ">", "|"):
        name = name.replace(token, "_")
    name = name.strip().strip(".")
    return name or fallback
