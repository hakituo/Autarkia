"""扫描图片、调用 VL 打标、并发编排。"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

from core.utils.logger import get_logger

from .paths import EXCLUDED_DIRS, MEMES_ROOT, SUPPORTED_EXTS
from .prompt import VL_PROMPT, VL_VISION_MODEL, parse_vl_output
from .store import load_existing, save_descriptions

logger = get_logger("meme_describe_runner")

#: 每处理多少张落盘一次（支持断点续传）
SAVE_EVERY = 20
#: 并发下取消 client 内置的全局最小间隔（串行时仍走默认 1.2s）
CONCURRENCY_MIN_INTERVAL = 0.0


def list_meme_images(only: str | None = None) -> list[Path]:
    """扫描 data/memes/ 下所有图片（排除 manual、_index、_inbox），返回 Path 列表。

    支持两种目录结构：
    - memes/<cat>/*.png  （一级子目录直接放图片）
    - memes/<cat>/<sub>/*.png  （二级子目录，如 normal/1/*.png）
    """
    if not MEMES_ROOT.is_dir():
        return []
    images: list[Path] = []

    if only:
        sub = MEMES_ROOT / only
        if not sub.is_dir():
            logger.error(f"子目录不存在: {sub}")
            return []
        targets = [sub]
    else:
        targets = [
            sub
            for sub in sorted(MEMES_ROOT.iterdir())
            if sub.is_dir() and sub.name.lower() not in EXCLUDED_DIRS
        ]

    for sub in targets:
        for img in sorted(sub.rglob("*")):
            if not img.is_file() or img.suffix.lower() not in SUPPORTED_EXTS:
                continue
            if any(
                part.lower() in EXCLUDED_DIRS for part in img.relative_to(MEMES_ROOT).parts
            ):
                continue
            images.append(img)
    return images


def encode_image_b64(path: Path) -> str | None:
    """读取图片并编码为 data URL。"""
    ext = path.suffix.lower().lstrip(".")
    if ext == "jpg":
        mime = "image/jpeg"
    elif ext == "webp":
        mime = "image/webp"
    else:
        mime = f"image/{ext}"
    try:
        with open(path, "rb") as f:
            data = f.read()
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception as e:  # noqa: BLE001 - 单张读不出来跳过，不中断整批
        logger.error(f"读取图片失败 {path}: {e}")
        return None


async def describe_one(client, image_path: Path) -> dict[str, Any] | None:
    """调 SiliconFlowClient 的 VL 接口给一张图生成场景导向描述。"""
    data_url = encode_image_b64(image_path)
    if not data_url:
        return None
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": VL_PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    ]
    # max_tokens 提到 220：场景描述 + tags + text 需要更多 token
    result = await client._vision_inference(messages, max_tokens=220, temperature=0.4)
    if result.get("status") != "success":
        logger.error(f"VL 失败 {image_path.name}: {result.get('error')}")
        return None
    parsed = parse_vl_output(str(result.get("text") or "").strip())
    if parsed:
        logger.info(f"  → {parsed.get('caption', '')[:50]}...")
    return parsed


async def _describe_with_retry(client, image_path: Path) -> dict[str, Any] | None:
    """单张最多尝试两次，失败返回 None。"""
    for attempt in range(2):
        try:
            info = await describe_one(client, image_path)
            if info:
                return info
        except Exception as e:  # noqa: BLE001 - 单张异常重试一次后放弃
            logger.warning(f"  尝试 {attempt + 1} 失败: {e}")
            await asyncio.sleep(1.0)
    return None


async def run(
    force: bool = False,
    only: str | None = None,
    limit: int | None = None,
    concurrency: int = 8,
) -> int:
    """主流程：增量给未打标的图片生成描述，返回本次新增条数。"""
    # 延迟导入避免循环依赖
    from core.llm.siliconflow_client import SiliconFlowClient

    images = list_meme_images(only=only)
    if not images:
        logger.error(f"未在 {MEMES_ROOT} 找到任何图片")
        return 0

    existing = {} if force else load_existing()
    logger.info(f"扫描到 {len(images)} 张图片，已有描述 {len(existing)} 条")

    todo: list[tuple[str, Path]] = []
    for img in images:
        rel = str(img.relative_to(MEMES_ROOT)).replace("\\", "/")
        if not force and rel in existing and existing[rel].get("caption"):
            continue
        todo.append((rel, img))
    if limit and limit > 0:
        todo = todo[:limit]
    logger.info(f"待打标 {len(todo)} 张，并发 {max(1, concurrency)}")
    if not todo:
        return 0

    client = SiliconFlowClient(vision_model=VL_VISION_MODEL)
    # Qwen3-VL-32B-Instruct 生成场景描述偶尔需要超过 60s，提到 120s
    client.timeout = 120
    if not client.api_key:
        logger.error("未设置 SILICONFLOW_API_KEY 环境变量，无法调用 VL 模型")
        return 0
    if concurrency > 1:
        # 并发时取消全局 1.2s 限速，否则并发退化为串行
        client._min_interval_sec = CONCURRENCY_MIN_INTERVAL

    descs: dict[str, dict[str, Any]] = dict(existing) if not force else {}
    semaphore = asyncio.Semaphore(max(1, concurrency))
    lock = asyncio.Lock()
    counters = {"processed": 0}
    failed: list[str] = []

    async def _worker(rel: str, img: Path) -> None:
        async with semaphore:
            info = await _describe_with_retry(client, img)
        async with lock:
            if info:
                descs[rel] = info
                counters["processed"] += 1
                if counters["processed"] % SAVE_EVERY == 0:
                    await asyncio.to_thread(save_descriptions, descs)
                    logger.info(f"进度 {counters['processed']}/{len(todo)}")
            else:
                failed.append(rel)

    await asyncio.gather(*(_worker(rel, img) for rel, img in todo))
    await asyncio.to_thread(save_descriptions, descs)

    if failed:
        logger.warning(f"{len(failed)} 张图描述失败：{failed[:5]}...")
    logger.info(
        f"完成：新增 {counters['processed']} 条，累计 {len(descs)} 条，"
        f"失败 {len(failed)} 条"
    )
    return counters["processed"]
