"""表情包素材源配置加载（来源：config/yaml/meme_sources.yaml）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from core.utils.logger import get_logger

logger = get_logger("meme_fetch_config")

#: 配置文件相对仓库根的位置
CONFIG_RELPATH = Path("config") / "yaml" / "meme_sources.yaml"


@dataclass
class NormalizePolicy:
    """图片规整参数。"""

    max_side: int = 600
    max_bytes: int = 600_000
    gif_max_bytes: int = 3_000_000
    min_bytes: int = 1024
    min_side: int = 64


@dataclass
class SourceSpec:
    """单个素材源的声明。"""

    source_id: str
    kind: str
    enabled: bool = True
    topic_id: int = 0
    page_size: int = 3000
    max_pages: int = 1
    title_keywords: list[str] = field(default_factory=list)
    title_require_any: list[str] = field(default_factory=list)
    title_excludes: list[str] = field(default_factory=list)
    accepted_exts: list[str] = field(default_factory=list)
    max_images_per_post: int = 0
    max_images: int = 0
    timeout_seconds: int = 60
    concurrency: int = 8


@dataclass
class FetchConfig:
    """整份配置的运行时形态。"""

    repo_root: Path
    inbox_root: Path
    normalize: NormalizePolicy
    max_total_files: int
    sources: dict[str, SourceSpec]

    def source_dir(self, source_id: str) -> Path:
        """某源在 inbox 下的落地目录。"""
        return self.inbox_root / source_id


def _as_list(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    return [str(item) for item in raw if str(item or "").strip()]


def _build_source(source_id: str, raw: dict[str, Any]) -> SourceSpec:
    return SourceSpec(
        source_id=source_id,
        kind=str(raw.get("kind") or "").strip(),
        enabled=bool(raw.get("enabled", True)),
        topic_id=int(raw.get("topic_id") or 0),
        page_size=int(raw.get("page_size") or 3000),
        max_pages=int(raw.get("max_pages") or 1),
        title_keywords=_as_list(raw.get("title_keywords")),
        title_require_any=_as_list(raw.get("title_require_any")),
        title_excludes=_as_list(raw.get("title_excludes")),
        accepted_exts=[e.lower() for e in _as_list(raw.get("accepted_exts"))],
        max_images_per_post=int(raw.get("max_images_per_post") or 0),
        max_images=int(raw.get("max_images") or 0),
        timeout_seconds=int(raw.get("timeout_seconds") or 60),
        concurrency=int(raw.get("concurrency") or 8),
    )


def load_config(repo_root: Path) -> FetchConfig:
    """读取并校验配置；缺文件或格式错误直接抛 ValueError。"""
    path = repo_root / CONFIG_RELPATH
    if not path.is_file():
        raise ValueError(f"素材源配置不存在: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise ValueError(f"素材源配置解析失败: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise TypeError(f"素材源配置顶层必须是映射: {path}")

    normalize_raw = raw.get("normalize") or {}
    if not isinstance(normalize_raw, dict):
        normalize_raw = {}
    normalize = NormalizePolicy(
        max_side=int(normalize_raw.get("max_side") or 600),
        max_bytes=int(normalize_raw.get("max_bytes") or 600_000),
        gif_max_bytes=int(normalize_raw.get("gif_max_bytes") or 3_000_000),
        min_bytes=int(normalize_raw.get("min_bytes") or 1024),
        min_side=int(normalize_raw.get("min_side") or 64),
    )

    inbox_raw = str(raw.get("inbox_root") or "data/memes/_inbox")
    inbox_root = (repo_root / inbox_raw).resolve()

    raw_sources = raw.get("sources") or {}
    if not isinstance(raw_sources, dict):
        raise TypeError(f"素材源配置 sources 必须是映射: {path}")
    sources: dict[str, SourceSpec] = {}
    for source_id, item in raw_sources.items():
        if not isinstance(item, dict):
            continue
        spec = _build_source(str(source_id), item)
        if spec.enabled:
            sources[spec.source_id] = spec

    if not sources:
        raise ValueError(f"素材源配置里没有启用的源: {path}")

    return FetchConfig(
        repo_root=repo_root,
        inbox_root=inbox_root,
        normalize=normalize,
        max_total_files=int(raw.get("max_total_files") or 0),
        sources=sources,
    )


def select_sources(
    config: FetchConfig, only: list[str] | None = None
) -> list[SourceSpec]:
    """按 --sources 过滤；未指定则返回全部启用源。未知 id 抛 ValueError。"""
    if not only:
        return list(config.sources.values())
    unknown = [name for name in only if name not in config.sources]
    if unknown:
        raise ValueError(
            f"未知素材源: {', '.join(unknown)}；可用: {', '.join(sorted(config.sources))}"
        )
    return [config.sources[name] for name in only]
