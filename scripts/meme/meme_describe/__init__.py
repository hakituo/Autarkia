"""表情包描述生成子包。

入口是上层薄壳 ``scripts/meme/build_meme_descriptions.py``，本包按职责拆分：
- ``paths``   目录与扩展名常量
- ``prompt``  VL 提示词与输出解析
- ``store``   descriptions.json 读写
- ``runner``  扫描 / 并发打标 / 落盘编排
"""

from __future__ import annotations

__all__ = ["paths", "prompt", "runner", "store"]
