# -*- coding: utf-8 -*-
"""读取 LLM 用量日志（JSONL）并归一为聚合可用的记录。

数据源是 ``core.llm.llm_logger.log_llm_usage`` 追加写入的
``logs/prompt_cache_stats.log``，第一条记录始于 2026-08-16。

字段兼容：
- 历史记录只有 prompt 侧（hit/miss/cache_write/prompt_tokens），没有
  completion_tokens / total_tokens，本模块把缺失值保持为 ``None``，
  聚合时按「未记录」处理，不当作 0 偷偷拉低输出统计；
- prompt_tokens 缺失时回退 hit+miss（2026-08 初期的少量记录）；
- 时间戳无时区时按系统配置时区补齐。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from core.utils.shared_roots import get_logs_root

STATS_LOG_NAME = "prompt_cache_stats.log"


def get_stats_log_path() -> Path:
    """返回用量日志路径（与 llm_logger 的写入点共用同一个 logs 根）。"""
    return get_logs_root() / STATS_LOG_NAME


def _optional_int(value: Any) -> Optional[int]:
    """把日志字段转成 int；缺失或非法返回 None（与 0 区分）。"""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_timestamp(value: Any) -> Optional[datetime]:
    """解析日志里的 ISO 时间戳；无时区时按系统配置时区补齐。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        try:
            from core.utils.time.time_utils import get_current_time

            parsed = parsed.replace(tzinfo=get_current_time().tzinfo)
        except Exception:
            return parsed
    return parsed


def normalize_record(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把一条原始日志归一为统计记录；时间戳非法时返回 None。"""
    if not isinstance(raw, dict):
        return None
    ts = parse_timestamp(raw.get("timestamp"))
    if ts is None:
        return None

    hit = _optional_int(raw.get("hit_tokens")) or 0
    miss = _optional_int(raw.get("miss_tokens")) or 0
    cache_write = _optional_int(raw.get("cache_write_tokens")) or 0
    prompt = _optional_int(raw.get("prompt_tokens"))
    if prompt is None:
        prompt = hit + miss
    completion = _optional_int(raw.get("completion_tokens"))
    reasoning = _optional_int(raw.get("reasoning_tokens")) or 0
    total = _optional_int(raw.get("total_tokens"))
    if total is None:
        # 历史记录没有 total_tokens，只能按「输入 + 已记录的输出」估算
        total = prompt + (completion or 0)

    return {
        "ts": ts,
        "date": ts.strftime("%Y-%m-%d"),
        "month": ts.strftime("%Y-%m"),
        "provider": str(raw.get("provider") or "unknown"),
        "model": str(raw.get("model") or "unknown"),
        "key_id": str(raw.get("key_id") or ""),
        "source": str(raw.get("source") or ""),
        "mode": str(raw.get("mode") or ""),
        "level": str(raw.get("level") or "N/A"),
        "hit_tokens": hit,
        "miss_tokens": miss,
        "cache_write_tokens": cache_write,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "total_tokens": total,
        "has_completion": completion is not None,
        "has_cache": (hit + miss) > 0,
    }


def iter_records(log_path: Optional[Path] = None) -> Iterator[Dict[str, Any]]:
    """逐行读取日志；坏行与非法时间戳静默跳过，不中断统计。"""
    path = Path(log_path) if log_path is not None else get_stats_log_path()
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                raw = json.loads(text)
            except json.JSONDecodeError:
                continue
            record = normalize_record(raw)
            if record is not None:
                yield record


def load_records(log_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """读取全部记录（按日志写入顺序）。"""
    return list(iter_records(log_path))
