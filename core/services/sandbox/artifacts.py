"""请求级产物收集：让沙箱产物能回传到聊天结果。

为什么不直接改 handler 的数据流：
产物路径只在「同一次请求内」有效，跨请求必须隔离，而 handler 的返回
结构被大量调用方和测试依赖，改动面大。ContextVar 天然按 async task
隔离，正好匹配这个语义——工具执行与响应构建在同一个 task 内完成。

用法::

    工具执行后   → record_artifacts(paths)
    构建响应时   → take_artifacts()   # 读取并清空
"""

from __future__ import annotations

import contextvars
from pathlib import Path
from typing import Iterable, List, Tuple

_artifacts: contextvars.ContextVar[Tuple[str, ...]] = contextvars.ContextVar(
    "sandbox_artifacts", default=()
)

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"})


def record_artifacts(paths: Iterable[str]) -> None:
    """记录本次请求产生的产物路径（可多次调用，自动去重保序）。"""
    new_items = tuple(str(p) for p in (paths or ()) if p)
    if not new_items:
        return
    current = _artifacts.get()
    _artifacts.set(tuple(dict.fromkeys((*current, *new_items))))


def take_artifacts() -> List[str]:
    """读取并清空本次请求的产物路径，避免污染后续请求。"""
    current = _artifacts.get()
    _artifacts.set(())
    return list(current)


def pick_image(artifacts: Iterable[str]) -> str:
    """从产物里挑出第一张图片路径；没有图片时返回空串。"""
    for item in artifacts or ():
        if Path(str(item)).suffix.lower() in IMAGE_EXTENSIONS:
            return str(item)
    return ""


def apply_to_result(result: dict) -> None:
    """把本次请求的沙箱产物写进响应字典。

    封装成单个入口是为了让调用方（响应构建处）只加一行，
    避免核心文件因为这段逻辑而超出单文件行数门禁。

    - ``artifacts``：本次产生的全部产物路径
    - ``image_path``：第一张图片的本地路径
    - ``image_url``：同一张图片的可访问 URL。**前端 WebSocket 推送读的是
      ``image_url``**，只给本地路径前端拿不到图；``output/`` 已挂载在 ``/output``。
    """
    try:
        artifacts = take_artifacts()
    except Exception:
        return
    if not artifacts:
        return
    result["artifacts"] = artifacts
    image = pick_image(artifacts)
    if not image:
        return
    result["image_path"] = image
    try:
        from core.image.image_utils import get_image_url

        result["image_url"] = get_image_url(image)
    except Exception:
        pass
