"""抓取编排：按源拉取 → 内容去重 → 规整落盘 → 写回增量状态。"""

from __future__ import annotations

from dataclasses import dataclass

from core.utils.logger import get_logger

from .config import FetchConfig, SourceSpec
from .media import WriteStats, content_hash, store_bytes
from .state import FetchState

logger = get_logger("meme_fetch_runner")


@dataclass
class SourceResult:
    """单个源的运行结果。"""

    source_id: str
    ok: bool = True
    error: str = ""
    stats: WriteStats | None = None

    def summary(self) -> str:
        if not self.ok:
            return f"{self.source_id}: 失败 - {self.error}"
        s = self.stats or WriteStats()
        return (
            f"{self.source_id}: 新增 {s.written} 张（{s.bytes_written / 1024 / 1024:.1f} MB）、"
            f"重复跳过 {s.duplicates}、过小 {s.skipped_small}、过大 {s.skipped_oversize}、"
            f"失败 {s.failed}"
        )


class _Budget:
    """全局写入额度，防止一次抓取把磁盘灌满。"""

    def __init__(self, total: int) -> None:
        self.remaining = total if total > 0 else None

    def take(self) -> bool:
        if self.remaining is None:
            return True
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


async def _run_miyoushe_source(
    spec: SourceSpec,
    config: FetchConfig,
    stats: WriteStats,
    state: FetchState,
    budget: _Budget,
    *,
    limit: int,
) -> None:
    """米游社话题源：拉帖 → 标题筛选 → 并发下载 → 去重落盘。"""
    from . import miyoushe

    posts = await miyoushe.fetch_posts(spec)
    matched = miyoushe.match_posts(posts, spec)
    if not matched:
        logger.warning(f"{spec.source_id}: 没有标题命中的帖子，检查 title_keywords")
        return
    images = miyoushe.collect_images(matched, spec)
    if limit:
        images = images[:limit]

    out_root = config.source_dir(spec.source_id)
    for item, data in await miyoushe.download_all(spec, images):
        if data is None:
            stats.failed += 1
            continue
        digest = content_hash(data)
        if state.known(digest):
            stats.duplicates += 1
            continue
        if not budget.take():
            continue
        dst = out_root / item.subdir / item.filename
        if store_bytes(data, dst, config.normalize, stats):
            state.record(digest, dst.relative_to(config.inbox_root).as_posix())


async def run_fetch(
    config: FetchConfig,
    sources: list[SourceSpec],
    *,
    limit: int = 0,
) -> list[SourceResult]:
    """依次跑各个源；单源失败不影响其它源。"""
    config.inbox_root.mkdir(parents=True, exist_ok=True)
    state = await FetchState.load(config.inbox_root)
    logger.info(f"暂存目录: {config.inbox_root}（已有 {len(state.hashes)} 条去重指纹）")
    budget = _Budget(config.max_total_files)

    results: list[SourceResult] = []
    for spec in sources:
        stats = WriteStats()
        result = SourceResult(source_id=spec.source_id, stats=stats)
        logger.info(f"=== 开始抓取 {spec.source_id}（{spec.kind}）===")
        try:
            if spec.kind == "miyoushe_topic":
                await _run_miyoushe_source(spec, config, stats, state, budget, limit=limit)
            else:
                raise ValueError(f"未知源类型: {spec.kind}")
        except Exception as exc:  # noqa: BLE001 - 单源失败记录后继续
            result.ok = False
            result.error = str(exc)
            logger.warning(f"{spec.source_id} 抓取失败: {exc}")
        results.append(result)
        state.record_source(
            spec.source_id,
            {
                "written": stats.written,
                "duplicates": stats.duplicates,
                "skipped_small": stats.skipped_small,
                "skipped_oversize": stats.skipped_oversize,
                "failed": stats.failed,
                "bytes_written": stats.bytes_written,
            },
        )
        await state.save()
        logger.info(result.summary())

    await state.save()
    return results
