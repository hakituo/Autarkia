"""表情包描述生成的路径与扫描常量。"""

from __future__ import annotations

from pathlib import Path

# scripts/meme/meme_describe/paths.py -> 仓库根
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# 表情包根目录
MEMES_ROOT = PROJECT_ROOT / "data" / "memes"

# 排除的子目录（小写匹配）：manual 是敏感素材，_index 是索引，_inbox 是抓取暂存区。
# 注意 normal 不在此列 —— 它虽然不是分类名，但里面的图要打标后才能被自然语言命中。
EXCLUDED_DIRS = {"manual", "_index", "_inbox"}

# 输出目录与文件
INDEX_DIR = MEMES_ROOT / "_index"
DESCRIPTIONS_PATH = INDEX_DIR / "descriptions.json"

# 支持的图片扩展名
SUPPORTED_EXTS = (".gif", ".jpg", ".jpeg", ".png", ".webp")
