# -*- coding: utf-8 -*-
"""价目表配置读取（``config/yaml/model_pricing.yaml``）。

不挂进 pydantic 配置树：价格源开关、超时、人工覆盖属于看板的取数口径，
改完要能立刻生效，不该要求主服务重启，也不该和模型运行参数混在一起。
配置文件缺失或损坏时退回 ``DEFAULTS``，读取失败不抛异常——统计侧不能
因为一个可选能力配不上而整体不可用。
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Optional

from core.utils.project_root import get_project_root
from core.utils.logger import get_logger

logger = get_logger("MODEL_PRICING_CONFIG")

#: 配置文件相对项目根的位置
CONFIG_REL_PATH = Path("config") / "yaml" / "model_pricing.yaml"

#: 与 model_pricing.yaml 同构的兜底默认值
DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "snapshot_path": "data/model_pricing.json",
    "refresh_after_seconds": 21600,
    "fetch_timeout_seconds": 12.0,
    "eager_wait_seconds": 2.5,
    "sources": {
        "openrouter": {
            "enabled": True,
            "url": "https://openrouter.ai/api/v1/models",
        },
        "deepseek_official": {
            "enabled": True,
            "url": "https://api-docs.deepseek.com/quick_start/pricing/",
            "model_aliases": {
                "deepseek-flash": "deepseek-v4-flash",
                "deepseek-v4-flash": "deepseek-v4-flash",
                "deepseek-pro": "deepseek-v4-pro",
                "deepseek-v4-pro": "deepseek-v4-pro",
            },
            "peak_schedule": {
                "timezone": "UTC",
                "weekdays": [1, 2, 3, 4, 5],
                "hour_ranges": [[1, 4], [6, 10]],
                "off_peak_divisor": 2.0,
            },
        },
    },
    "vendor_from_key_prefix": True,
    "slashed_model_vendor": "openrouter",
    "price_free_suffix": True,
    "display_currency": "USD",
    "usd_to_cny": 7.08,
    "overrides": {},
}

#: 上一次读到的配置与其文件指纹，用于「改了 YAML 立刻生效」
_CACHE: Dict[str, Any] = {"signature": None, "config": None}


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并字典：override 里的 dict 与 base 的 dict 逐键合并，其余直接覆盖。"""
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def config_path() -> Path:
    """返回价目表配置文件路径。"""
    return get_project_root() / CONFIG_REL_PATH


def _file_signature(path: Path) -> Optional[tuple]:
    """取文件指纹；文件不存在返回 None。"""
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def get_pricing_config(force_reload: bool = False) -> Dict[str, Any]:
    """读取价目表配置，缺失字段用 ``DEFAULTS`` 补齐。

    Args:
        force_reload: 忽略文件指纹，强制重读磁盘
    """
    path = config_path()
    signature = _file_signature(path)
    if not force_reload and _CACHE["config"] is not None and _CACHE["signature"] == signature:
        return _CACHE["config"]

    loaded: Dict[str, Any] = {}
    if signature is not None:
        try:
            import yaml

            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict):
                loaded = raw.get("pricing") if isinstance(raw.get("pricing"), dict) else raw
        except Exception as exc:  # YAML 写坏了也不能让看板打不开
            logger.warning("价目表配置解析失败，使用默认值: %s", exc)
            loaded = {}

    config = _merge(DEFAULTS, loaded or {})
    _CACHE["signature"] = signature
    _CACHE["config"] = config
    return config


def snapshot_path(config: Optional[Dict[str, Any]] = None) -> Path:
    """返回价格快照的落盘路径（相对路径按项目根解析）。"""
    cfg = config or get_pricing_config()
    raw = str(cfg.get("snapshot_path") or DEFAULTS["snapshot_path"])
    path = Path(raw).expanduser()
    return path if path.is_absolute() else get_project_root() / path


def reset_config_cache() -> None:
    """清空配置缓存（测试用）。"""
    _CACHE["signature"] = None
    _CACHE["config"] = None
