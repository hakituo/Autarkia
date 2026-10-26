"""米游社「表情包」话题源：抓官方连载系列贴里的原图。

接口要点（2026-10 实测）：
- 端点 ``/post/wapi/getTopicPostList``，分页游标是 **last_id**，
  page / offset / page_num 等参数全部无效（会一直返回第一页）；
- page_size 可到 3000，单次即可覆盖数千帖；
- 响应结构是 ``data.posts[].post``，图片直链在 ``post.images`` 数组；
- 图床 ``upload-bbs.miyoushe.com`` 裸 GET 即可下载，不需要 Referer。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from core.utils.logger import get_logger

from .config import SourceSpec
from .media import safe_name

logger = get_logger("meme_fetch_miyoushe")

API_URL = "https://bbs-api.miyoushe.com/post/wapi/getTopicPostList"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://bbs.miyoushe.com/",
    "Accept": "application/json, text/plain, */*",
}

#: 主题贴子标题在目录名里的最大长度
_TITLE_MAX = 24


@dataclass
class RemoteImage:
    """待下载的远端图片及其来源信息。"""

    url: str
    post_id: str
    title: str
    index: int

    @property
    def filename(self) -> str:
        """形如 ``79037025-01.png``。"""
        ext = self.url.rsplit(".", 1)[-1].lower()
        if ext not in ("png", "jpg", "jpeg", "gif", "webp"):
            ext = "png"
        return f"{self.post_id}-{self.index:02d}.{ext}"

    @property
    def subdir(self) -> str:
        """按「帖子 id + 标题片段」分组，筛选时能看出系列来源。"""
        return f"{self.post_id}-{safe_name(self.title, 'untitled')[:_TITLE_MAX]}"


async def _get_json(session, url: str, timeout: int) -> dict[str, Any]:
    async with session.get(url, timeout=timeout) as response:
        response.raise_for_status()
        return await response.json(content_type=None)


async def fetch_posts(spec: SourceSpec) -> list[dict[str, Any]]:
    """按 last_id 游标翻页拉取话题贴，返回 post 字典列表。"""
    import aiohttp

    posts: list[dict[str, Any]] = []
    last_id: str | None = None
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        for page in range(max(1, spec.max_pages)):
            url = f"{API_URL}?topic_id={spec.topic_id}&page_size={spec.page_size}&gids=2&sort_type=2"
            if last_id:
                url = f"{url}&last_id={last_id}"
            try:
                payload = await _get_json(session, url, spec.timeout_seconds)
            except Exception as exc:  # noqa: BLE001 - 单页失败就停在这页
                logger.warning(f"拉取话题贴失败（第 {page + 1} 页）: {exc}")
                break
            data = payload.get("data") or {}
            batch = [item.get("post") for item in (data.get("posts") or []) if item.get("post")]
            posts.extend(batch)
            logger.info(f"话题 {spec.topic_id} 第 {page + 1} 页：{len(batch)} 帖（累计 {len(posts)}）")
            last_id = str(data.get("last_id") or "")
            if not last_id or data.get("is_last"):
                break
    return posts


def match_posts(posts: list[dict[str, Any]], spec: SourceSpec) -> list[dict[str, Any]]:
    """按标题筛出目标贴。

    三层过滤，按顺序：
    1. 排除词（求图 / 提问帖）直接丢弃；
    2. `title_keywords` 至少要命中一个（内容类型：表情包 / 贴纸 / Q版 …）；
    3. `title_require_any` 至少要命中一个（二游特征：游戏名 / 角色名 / 官方），
       避免把「弱弱老师表情包」这类非二游内容混进来。
    """
    keywords = [k for k in spec.title_keywords if k]
    require_any = [k for k in spec.title_require_any if k]
    excludes = [k for k in spec.title_excludes if k]
    matched: list[dict[str, Any]] = []
    excluded_hits = 0
    off_topic = 0
    for post in posts:
        title = str(post.get("subject") or "").strip()
        if not post.get("images"):
            continue
        if excludes and any(k in title for k in excludes):
            excluded_hits += 1
            continue
        if keywords and not any(k in title for k in keywords):
            continue
        if require_any and not any(k in title for k in require_any):
            off_topic += 1
            continue
        matched.append(post)
    logger.info(
        f"标题命中 {len(matched)} 帖 / 候选 {len(posts)} 帖"
        f"（排除词滤掉 {excluded_hits} 帖，非二游滤掉 {off_topic} 帖）"
    )
    return matched


def _url_ext(url: str) -> str:
    """取 URL 路径部分的扩展名（忽略查询串），返回小写带点形式。"""
    path = urlsplit(url).path
    suffix = Path(path).suffix.lower()
    return suffix


def collect_images(posts: list[dict[str, Any]], spec: SourceSpec) -> list[RemoteImage]:
    """把命中帖里的图片展开成待下载列表。

    - 按 `accepted_exts` 白名单过滤格式（默认只收静态图，动图 GIF 一律跳过）；
    - 单帖按过滤后的顺序取前 N 张，同帖内按 URL 去重。
    """
    accepted = {e.lower() for e in spec.accepted_exts if e}
    images: list[RemoteImage] = []
    skipped_dynamic = 0
    for post in posts:
        post_id = str(post.get("post_id") or "")
        title = str(post.get("subject") or "").strip()
        urls = [str(u) for u in (post.get("images") or []) if str(u).startswith("http")]
        if accepted:
            kept = []
            for url in urls:
                if _url_ext(url) in accepted:
                    kept.append(url)
                else:
                    skipped_dynamic += 1
            urls = kept
        if spec.max_images_per_post > 0:
            urls = urls[: spec.max_images_per_post]
        seen: set[str] = set()
        for idx, url in enumerate(urls, 1):
            if url in seen:
                continue
            seen.add(url)
            images.append(RemoteImage(url=url, post_id=post_id, title=title, index=idx))
    if spec.max_images > 0:
        images = images[: spec.max_images]
    logger.info(
        f"待下载图片 {len(images)} 张（按格式白名单跳过 {skipped_dynamic} 张）"
    )
    return images


async def download_all(
    spec: SourceSpec, images: list[RemoteImage]
) -> list[tuple[RemoteImage, bytes | None]]:
    """并发下载，返回 [(图片信息, 字节内容或 None)]。

    单张失败只记为 None，不中断整批。
    """
    import aiohttp

    semaphore = asyncio.Semaphore(max(1, spec.concurrency))
    results: list[tuple[RemoteImage, bytes | None]] = []

    async with aiohttp.ClientSession(headers=HEADERS) as session:

        async def _one(item: RemoteImage) -> tuple[RemoteImage, bytes | None]:
            async with semaphore:
                try:
                    async with session.get(item.url, timeout=spec.timeout_seconds) as response:
                        response.raise_for_status()
                        return item, await response.read()
                except Exception as exc:  # noqa: BLE001 - 单张失败跳过
                    logger.debug(f"下载失败 {item.url}: {exc}")
                    return item, None

        tasks = [_one(item) for item in images]
        for index, coro in enumerate(asyncio.as_completed(tasks), 1):
            results.append(await coro)
            if index % 20 == 0 or index == len(tasks):
                logger.info(f"下载进度 {index}/{len(tasks)}")
    return results
