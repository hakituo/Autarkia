"""表情包描述生成脚本（薄壳入口）

遍历 data/memes/ 下所有图片（排除 manual / _index / _inbox），调用 SiliconFlow VL 模型
给每张图生成中文场景描述，输出到 data/memes/_index/descriptions.json。

特性：
- 增量处理：已生成 caption 的图片不重复处理
- 并发打标：默认 8 并发（`--concurrency` 可调），失败单张最多重试 2 次
- 支持断点续传：每 20 张落盘一次，随时 Ctrl+C，下次继续
- 支持 --only 子目录参数，只处理指定分类

用法：
    python -m scripts.meme.build_meme_descriptions
    python -m scripts.meme.build_meme_descriptions --force  # 强制重建
    python -m scripts.meme.build_meme_descriptions --only normal  # 只处理 normal 子目录
    python -m scripts.meme.build_meme_descriptions --only normal --concurrency 16
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# 支持直接运行（python scripts/meme/build_meme_descriptions.py）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.meme.meme_describe.runner import run  # 依赖上方 sys.path 注入


def main() -> int:
    parser = argparse.ArgumentParser(description="生成表情包中文描述")
    parser.add_argument("--force", action="store_true", help="强制重建（忽略已有描述）")
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="只处理指定子目录（如 normal），不指定则处理全部",
    )
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 张（测试用）")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="并发打标数（默认 %(default)s；调大更快但更吃 API 配额）",
    )
    args = parser.parse_args()
    count = asyncio.run(
        run(
            force=args.force,
            only=args.only,
            limit=args.limit,
            concurrency=args.concurrency,
        )
    )
    return 0 if count >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
