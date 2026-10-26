"""表情包素材抓取子包：从米游社「表情包」话题下载二游官方表情包到 data/memes/_inbox/。

入口是上层薄壳 ``scripts/meme/fetch_meme_library.py``（子目录不复用入口文件名，
避免同名包遮蔽同名模块导致 ``python -m`` 失败），本包只按职责拆分：
- ``config``    读 config/yaml/meme_sources.yaml
- ``media``     内容哈希去重、尺寸/体积规整、原子写入
- ``miyoushe``  米游社话题贴源（拉帖 / 标题筛选 / 并发下载）
- ``state``     增量状态（已入库指纹）
- ``runner``    编排
"""

from __future__ import annotations

__all__ = ["config", "media", "miyoushe", "runner", "state"]
