# -*- coding: utf-8 -*-
"""价目表同步：抓取 → 合并 → 交给 snapshot 落盘 → 懒刷新。

三条设计约束：

1. **绝不阻塞主业务**。取数路径只读本地快照文件；快照过期时在后台发起重抓，
   本次仍用旧快照返回。只有「本地完全没有快照」才愿意等，且等不超过
   ``eager_wait_seconds``，超时就先出空目录，下一次再补。
2. **抓失败不清空**。任一来源失败只影响它自己的状态位，其余来源与旧快照
   照常可用；全失败时保留上一份并标 ``last_error``。价格页改版不能把看板上
   的钱数变成 0。
3. **重算而非落库**。成本不落进用量日志，读的时候按当前价目表现算——
   厂商调价或补上人工覆盖之后，历史用量会自动按新价重新计价。

快照本身怎么读写见 ``snapshot.py``。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.llm.token_stats.pricing.models import (
    SOURCE_MANUAL,
    PriceCatalog,
    TokenPrice,
    normalize_model_id,
)
from core.llm.token_stats.pricing.settings import get_pricing_config, snapshot_path
from core.llm.token_stats.pricing.snapshot import (
    age_seconds,
    load_catalog,
    now_iso_local,
    read_snapshot,
    write_snapshot,
)
from core.llm.token_stats.pricing.sources import (
    fetch_json,
    fetch_text,
    parse_deepseek_official,
    parse_openrouter,
)
from core.utils.logger import get_logger

logger = get_logger("MODEL_PRICING_SYNC")

#: 正在跑的抓取任务，供外部 await 同一个任务而不是重复发起
_TASK: Optional["asyncio.Future"] = None


def manual_entries(overrides: Dict[str, Any]) -> List[TokenPrice]:
    """把 YAML 里的人工覆盖转成条目；人工条目优先级最高。"""
    entries: List[TokenPrice] = []
    for model_id, raw in (overrides or {}).items():
        if not isinstance(raw, dict):
            continue
        payload = dict(raw)
        payload["key"] = normalize_model_id(model_id)
        payload.setdefault("source", SOURCE_MANUAL)
        payload.setdefault("source_url", "config/yaml/model_pricing.yaml")
        entries.append(TokenPrice.from_dict(payload))
    return entries


def merge(entries_by_priority: List[List[TokenPrice]]) -> Dict[str, TokenPrice]:
    """按「靠前优先级更高」合并多来源条目，同键先到先得。"""
    merged: Dict[str, TokenPrice] = {}
    for entries in entries_by_priority:
        for entry in entries:
            if entry.key and entry.key not in merged:
                merged[entry.key] = entry
    return merged


async def _fetch_source(name: str, cfg: Dict[str, Any]) -> Tuple[List[TokenPrice], str]:
    """抓单个来源，返回 (条目, 峰谷原文)。失败抛异常，由调用方记录状态。"""
    url = str(cfg.get("url") or "")
    timeout = float(cfg.get("fetch_timeout_seconds") or 12.0)
    if not url:
        raise ValueError("来源未配置 url")
    if name == "openrouter":
        return parse_openrouter(await fetch_json(url, timeout), url), ""
    if name == "deepseek_official":
        return parse_deepseek_official(await fetch_text(url, timeout), url, cfg)
    raise ValueError(f"未知价格来源: {name}")


async def sync_once(config: Optional[Dict[str, Any]] = None) -> PriceCatalog:
    """抓一轮全部启用的来源并落盘；任何单源失败都只记录状态、不影响其余。"""
    cfg = config or get_pricing_config(force_reload=True)
    target: Path = snapshot_path(cfg)
    previous, _ = read_snapshot(target)
    sources_cfg: Dict[str, Any] = cfg.get("sources") or {}
    timeout = float(cfg.get("fetch_timeout_seconds") or 12.0)

    enabled = {
        name: dict(c) for name, c in sources_cfg.items() if isinstance(c, dict) and c.get("enabled")
    }
    names = list(enabled)
    results = (
        await asyncio.gather(
            *[
                _fetch_source(name, {**enabled[name], "fetch_timeout_seconds": timeout})
                for name in names
            ],
            return_exceptions=True,
        )
        if names
        else []
    )

    collected: Dict[str, List[TokenPrice]] = {}
    status: Dict[str, Dict[str, Any]] = {}
    notes: List[str] = []
    for name, result in zip(names, results):
        if isinstance(result, BaseException):
            reason = f"{type(result).__name__}: {result}"
            logger.warning("价格来源 %s 抓取失败: %s", name, reason)
            status[name] = {"ok": False, "error": reason[:240], "entries": 0}
            # 抓不到就沿用旧快照里来自该来源的条目，别让改版直接抹掉价格
            collected[name] = [p for p in previous.prices.values() if p.source == name]
            continue
        entries, note = result
        status[name] = {"ok": True, "entries": len(entries), "error": ""}
        collected[name] = entries
        if note:
            notes.append(note)

    for name in sources_cfg:
        if name not in status:
            status[name] = {"ok": None, "entries": 0, "error": "已停用", "skipped": True}

    succeeded = {name for name, st in status.items() if st.get("ok")}
    # 旧快照只兜底「这轮没成功抓到的来源」：抓成功的以最新列表为准，
    # 厂商下线或改了口径的型号要跟着消失，否则错价会永远留在目录里；
    # 人工覆盖每次都由 YAML 重建，删掉的条目不该被旧快照复活。
    carry_over = [
        price
        for price in previous.prices.values()
        if price.source not in succeeded and price.source != SOURCE_MANUAL
    ]

    # 人工覆盖 > 各来源按配置顺序 > 未成功来源的旧条目
    priority: List[List[TokenPrice]] = [manual_entries(cfg.get("overrides") or {})]
    priority += [collected[name] for name in names]
    priority.append(carry_over)

    catalog = PriceCatalog(
        prices=merge(priority),
        synced_at=now_iso_local(),
        sources=status,
        schedule_note=" ".join(notes) or previous.schedule_note,
    )
    write_snapshot(catalog, target)
    return catalog


def _sync_task(config: Optional[Dict[str, Any]] = None) -> "asyncio.Future":
    """单飞：已有在跑的任务就复用，避免连点刷新打出多个抓取。"""
    global _TASK
    if _TASK is not None and not _TASK.done():
        return _TASK
    _TASK = asyncio.ensure_future(sync_once(config))
    return _TASK


def is_stale(catalog: PriceCatalog, config: Optional[Dict[str, Any]] = None) -> bool:
    """快照是否过期（从没抓过也算过期）。"""
    cfg = config or get_pricing_config()
    ttl = float(cfg.get("refresh_after_seconds") or 0)
    if ttl <= 0:
        return True
    age = age_seconds(catalog)
    return age is None or age >= ttl


async def ensure_catalog(
    config: Optional[Dict[str, Any]] = None, force: bool = False
) -> PriceCatalog:
    """取当前可用目录：过期则后台重抓、本次先回旧数据；完全没快照时最多等一会儿。

    Args:
        force: 忽略 TTL 立刻重抓（看板「同步价格」按钮走这条路）
    """
    cfg = config or get_pricing_config()
    target = snapshot_path(cfg)
    if not cfg.get("enabled", True):
        return load_catalog(target)

    catalog = load_catalog(target)
    if not force and not is_stale(catalog, cfg):
        return catalog

    had_data = bool(catalog.prices)
    wait = float(cfg.get("eager_wait_seconds") or 2.5)
    task = _sync_task(cfg)
    if not had_data:
        # 冷启动：等一会儿，但等不到就先出空目录，不拖慢首屏
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=wait)
        except asyncio.TimeoutError:
            logger.info("首次价目表同步超过 %.1fs 未完成，先用空目录", wait)
            return catalog
        except Exception as exc:
            logger.warning("首次价目表同步失败: %s", exc)
            return catalog

    if not force:
        return catalog

    # 手动同步多等一会儿；shield 保证超时只是不再等，不会把后台任务掐掉
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=wait * 4)
    except asyncio.TimeoutError:
        logger.warning("手动同步价目表超过 %.0fs 未完成，先用旧快照", wait * 4)
        return catalog
    except Exception as exc:
        logger.warning("手动同步价目表失败: %s", exc)
        return catalog


def pricing_status(
    catalog: PriceCatalog, config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """组装给看板的价目表健康度信息。"""
    cfg = config or get_pricing_config()
    age = age_seconds(catalog)
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "entry_count": len(catalog.prices),
        "synced_at": catalog.synced_at,
        "age_seconds": round(age, 1) if age is not None else None,
        "stale": is_stale(catalog, cfg),
        "refresh_after_seconds": cfg.get("refresh_after_seconds"),
        "sources": catalog.sources,
        "schedule_note": catalog.schedule_note,
        "display_currency": cfg.get("display_currency") or "USD",
        "usd_to_cny": cfg.get("usd_to_cny"),
        "snapshot": str(snapshot_path(cfg)),
    }
