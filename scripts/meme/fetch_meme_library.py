"""表情包素材抓取脚本（薄壳入口）

把米游社「表情包」话题里的二游官方表情包下载到 data/memes/_inbox/<源 id>/ 下，
供**人工筛选**后再归入情绪分类目录；本脚本不做情绪归类。

源清单与抓取参数在 config/yaml/meme_sources.yaml，支持：
- 增量：按内容 md5 去重，重复运行只补新文件；
- 断点：每完成一个源就落一次 data/memes/_inbox/.state.json；
- 筛选：标题关键词命中 + 排除词过滤，只留官方系列 / 高清修复类帖子。

用法::

    python -m scripts.meme.fetch_meme_library                    # 抓全部启用的源
    python -m scripts.meme.fetch_meme_library --limit 20         # 最多写 20 张（试跑）
    python -m scripts.meme.fetch_meme_library --dry-run          # 只列出计划
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.logger import get_logger  # 依赖上方 sys.path 注入项目根目录
from scripts.meme.meme_fetch.config import (
    FetchConfig,
    load_config,
    select_sources,
)
from scripts.meme.meme_fetch.runner import run_fetch

logger = get_logger("fetch_meme_library")


def _print_plan(config: FetchConfig, sources: list) -> None:
    """dry-run：只输出将要执行的动作。"""
    print(f"[dry-run] 暂存目录：{config.inbox_root}")
    print(
        "[dry-run] 规整参数："
        f"max_side={config.normalize.max_side} "
        f"max_bytes={config.normalize.max_bytes} "
        f"min_bytes={config.normalize.min_bytes}"
    )
    for spec in sources:
        target = config.source_dir(spec.source_id)
        print(f"[dry-run] 源 {spec.source_id}（{spec.kind}）-> {target}")
        print(
            f"          话题={spec.topic_id}，翻 {spec.max_pages} 页，"
            f"最多 {spec.max_images or '不限'} 张 / 单帖 {spec.max_images_per_post or '不限'} 张"
        )
        print(f"          关键词：{'、'.join(spec.title_keywords) or '（不筛）'}")
        if spec.title_excludes:
            print(f"          排除词：{'、'.join(spec.title_excludes)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="抓取二游官方表情包到 data/memes/_inbox/")
    parser.add_argument(
        "--sources",
        nargs="+",
        default=None,
        help="只抓指定源（默认全部启用的源）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="最多写入多少张（试跑用，0 表示不限）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只输出计划，不下载也不写文件",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(PROJECT_ROOT)
        sources = select_sources(config, args.sources)
    except (TypeError, ValueError) as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        _print_plan(config, sources)
        return 0

    results = asyncio.run(run_fetch(config, sources, limit=max(0, args.limit)))

    print("\n=== 抓取汇总 ===")
    for result in results:
        print(f"  {result.summary()}")
    total = sum(r.stats.written for r in results if r.stats)
    print(f"  合计新增 {total} 张 -> {config.inbox_root}")
    print("  下一步：人工筛选后归入情绪分类，再跑 build_meme_descriptions / build_meme_vector_index")

    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
