# -*- coding: utf-8 -*-
"""价格来源适配器。

每个适配器只做一件事：把某个厂商的公开价目页抓回来、解析成
``TokenPrice`` 列表。解析不出来的型号宁可不给价，也不要瞎猜一个 0——
按 0 计会让「免费」和「取不到价」在看板上长得一模一样。

失败一律抛异常，由同步层决定「保留上一份快照并标记 stale」，
适配器自己不做兜底，避免把过期价悄悄当成最新价。
"""

from __future__ import annotations

import html as html_lib
import re
from typing import Any, Dict, List, Optional, Tuple

from core.llm.token_stats.pricing import net
from core.llm.token_stats.pricing.models import (
    SOURCE_DEEPSEEK_OFFICIAL,
    SOURCE_OPENROUTER,
    PeakSchedule,
    TokenPrice,
    normalize_model_id,
)

#: 厂商价格页普遍按「每 1M tokens」标价
_PER_MILLION = 1_000_000.0

#: 脚注标记，如 deepseek-flash(1) 里的 (1)
_FOOTNOTE = re.compile(r"\s*\(\d+\)\s*$|\s*[¹²³⁴⁵⁶⁷⁸⁹]+\s*$")
#: 价格单元格：$0.003 / ¥0.003 / 0.003
_MONEY = re.compile(r"^\s*[\$¥]?\s*(\d+(?:\.\d+)?)\s*$")


def _to_float(value: Any) -> Optional[float]:
    """把价格字段转成每 token 的浮点数；空串与 '0' 之外的非法值返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _per_token(value: Optional[float]) -> Optional[float]:
    """把「每 1M tokens」报价换算成「每 token」。"""
    return None if value is None else value / _PER_MILLION


def _published_rate(value: Any) -> Optional[float]:
    """读 OpenRouter 的每 token 价。

    ``-1`` 是它给「价格随实际路由到的模型而定」的哨兵值（auto / router 类模型），
    不是价。当价用会把成本算成负数，所以按「没有价」处理，让这类记录进待补价清单。
    """
    rate = _to_float(value)
    return None if rate is not None and rate < 0 else rate


async def fetch_json(url: str, timeout: float) -> Dict[str, Any]:
    """GET 一个 JSON 接口（带 UA，OpenRouter 对无 UA 的请求会限速）。"""
    async with net.client(
        url, timeout, "autarkia-token-dashboard/1.0", "application/json"
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"{url} 返回的不是 JSON 对象")
    return payload


async def fetch_text(url: str, timeout: float) -> str:
    """GET 一个 HTML 页面正文。"""
    async with net.client(
        url, timeout, "Mozilla/5.0 autarkia-token-dashboard/1.0", "text/html"
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


# --------------------------------------------------------------------------
# OpenRouter：公开 JSON，免密钥，一次给到全部托管模型
# --------------------------------------------------------------------------


def parse_openrouter(payload: Dict[str, Any], url: str) -> List[TokenPrice]:
    """把 OpenRouter /api/v1/models 的 pricing 段转成单价条目。

    字段口径：``prompt`` 是未命中输入、``input_cache_read`` 是命中读、
    ``input_cache_write`` 是写缓存，与用量日志里的 miss / hit / cache_write
    正好一一对应。``internal_reasoning`` 是厂商另计的推理费，本仓库的
    reasoning_tokens 已含在 completion 内，不重复加，只作为 note 提示。

    单位：这个接口返回的就是**每 token** 价（不同于厂商价格页的「每 1M tokens」），
    所以这里不做换算；同一份数据里 ``prompt`` 为 ``"0"`` 就是真的免费路由。
    """
    entries: List[TokenPrice] = []
    for model in payload.get("data") or []:
        if not isinstance(model, dict):
            continue
        raw_id = str(model.get("id") or "").strip()
        pricing = model.get("pricing") or {}
        if not raw_id or not isinstance(pricing, dict):
            continue
        prompt = _published_rate(pricing.get("prompt"))
        completion = _published_rate(pricing.get("completion"))
        if prompt is None and completion is None:
            continue
        extra = []
        if _to_float(pricing.get("internal_reasoning")):
            extra.append("厂商对 reasoning 另计价")
        if any(
            (_to_float(pricing.get(name)) or 0) < 0
            for name in ("prompt", "completion", "input_cache_read", "input_cache_write")
        ):
            extra.append("价格随实际路由的模型浮动，厂商未给固定价")
        entries.append(
            TokenPrice(
                key=normalize_model_id(raw_id),
                currency="USD",
                input=prompt,
                output=completion,
                cache_read=_published_rate(pricing.get("input_cache_read")),
                cache_write=_published_rate(pricing.get("input_cache_write")),
                source=SOURCE_OPENROUTER,
                source_url=url,
                note="；".join(extra),
            )
        )
    if not entries:
        raise ValueError("OpenRouter 模型列表里没解析出任何价格")
    return entries


# --------------------------------------------------------------------------
# DeepSeek 官方文档价格页：HTML 表格，含峰谷两档
# --------------------------------------------------------------------------

_METRIC_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("cache_read", r"INPUT\s+TOKENS\s*\(\s*CACHE\s*HIT"),
    ("input", r"INPUT\s+TOKENS\s*\(\s*CACHE\s*MISS"),
    ("output", r"OUTPUT\s+TOKENS"),
)


def _row_cells(row_html: str) -> List[str]:
    """取一行里各单元格的纯文本。"""
    cells: List[str] = []
    for inner in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row_html, re.S | re.I):
        text = re.sub(r"<[^>]+>", " ", inner)
        cells.append(" ".join(html_lib.unescape(text).split()))
    return cells


def _money_cells(cells: List[str]) -> List[Optional[float]]:
    """把行尾连续的金额单元格抽出来（元/1M tokens）。"""
    tail: List[Optional[float]] = []
    for cell in reversed(cells):
        match = _MONEY.match(cell)
        if not match:
            break
        tail.append(float(match.group(1)))
    return list(reversed(tail))


def _model_columns(rows: List[List[str]]) -> List[str]:
    """找表头 MODEL 行，返回列对应的展示名（已去脚注、已小写）。"""
    for cells in rows:
        if not cells:
            continue
        if re.match(r"^model\b", cells[0], re.I):
            names = []
            for cell in cells[1:]:
                cleaned = _FOOTNOTE.sub("", cell).strip().lower()
                if cleaned:
                    names.append(cleaned)
            if names:
                return names
    return []


def _row_labels(cells: List[str]) -> Tuple[str, str]:
    """从非金额单元格里读出 (指标, 峰谷档)。"""
    metric = ""
    period = ""
    for cell in cells:
        upper = cell.upper()
        for name, pattern in _METRIC_PATTERNS:
            if re.search(pattern, upper):
                metric = name
        if "OFF-PEAK" in upper:
            period = "off_peak"
        elif re.search(r"\bPEAK\b", upper):
            period = "peak"
    return metric, period


def parse_deepseek_official(
    page_html: str, url: str, config: Optional[Dict[str, Any]] = None
) -> Tuple[List[TokenPrice], str]:
    """解析 DeepSeek 官网价格表，返回 (单价列表, 峰谷原文说明)。

    表格是「行=指标×峰谷档、列=模型」的矩阵，且带 rowspan，所以不能按列数
    对齐，只能按「行尾连续金额单元格的个数 == 模型列数」来定位归属。
    """
    config = config or {}
    rows = [_row_cells(row) for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page_html, re.S | re.I)]
    rows = [cells for cells in rows if cells]
    columns = _model_columns(rows)
    if not columns:
        raise ValueError("价格页里找不到 MODEL 表头，页面结构可能已改版")

    aliases: Dict[str, str] = {
        normalize_model_id(k): str(v) for k, v in (config.get("model_aliases") or {}).items()
    }
    divisor = float(config.get("off_peak_divisor") or 2.0)
    schedule = PeakSchedule.from_dict(config.get("peak_schedule"))

    #: 模型名 → {档: {指标: 价格}}
    collected: Dict[str, Dict[str, Dict[str, Optional[float]]]] = {}
    for cells in rows:
        metric, period = _row_labels(cells)
        if not metric or not period:
            continue
        prices = _money_cells(cells)
        if len(prices) != len(columns):
            continue
        for name, price in zip(columns, prices):
            model = aliases.get(name, name)
            if not model:
                continue
            slot = collected.setdefault(model, {}).setdefault(period, {})
            slot[metric] = _per_token(price)

    if not collected:
        raise ValueError("价格页表头找到了，但没解析出任何价格行")

    entries: List[TokenPrice] = []
    for model, tiers in collected.items():
        off = dict(tiers.get("off_peak") or {})
        peak = dict(tiers.get("peak") or {})
        # 页面只印一档时按「峰价 = 谷价 × 倍数」补另一档：
        # 不补就会把峰价当常价（或反过来），整段时间的钱都算错
        if peak and not off:
            off = {
                name: (value / divisor if value is not None else None)
                for name, value in peak.items()
            }
        elif off and not peak:
            peak = {
                name: (value * divisor if value is not None else None)
                for name, value in off.items()
            }
        base = off or peak
        entries.append(
            TokenPrice(
                key=normalize_model_id(model),
                currency="USD",
                input=base.get("input"),
                output=base.get("output"),
                cache_read=base.get("cache_read"),
                cache_write=None,
                peak_input=peak.get("input"),
                peak_output=peak.get("output"),
                peak_cache_read=peak.get("cache_read"),
                schedule=schedule if (peak and off) else None,
                source=SOURCE_DEEPSEEK_OFFICIAL,
                source_url=url,
                note="直连官方 API 价，与经聚合网关托管的同型号不同",
            )
        )

    note_match = re.search(r"Peak hours are[^.<]*\.", html_lib.unescape(page_html), re.S)
    note = " ".join(re.sub(r"<[^>]+>", " ", note_match.group(0)).split()) if note_match else ""
    return entries, note
