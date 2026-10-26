# -*- coding: utf-8 -*-
"""LLM token 用量统计接口与看板页面。

数据只读：从 ``logs/prompt_cache_stats.log`` 聚合，不改动请求链路。
成本按当前价目表**读取时现算**，不写回日志（见 RULES 里的「重算而非落库」）。
看板页面本体是 ``static/token_stats/index.html``，既可通过 /static 直达，
也可用 ``/api/v1/token-stats/dashboard`` 访问。
"""

import asyncio
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from core.api.contract import error_response, success_response
from core.api.error_response import ErrorCode
from core.utils.logger import get_logger
from core.utils.project_root import get_project_root

logger = get_logger("TOKEN_STATS_ROUTER")

router = APIRouter(prefix="/token-stats", tags=["LLM 用量统计"])

#: 看板静态页相对项目根的位置
DASHBOARD_REL_PATH = Path("static") / "token_stats" / "index.html"


async def _catalog_or_none(force: bool = False):
    """取价目表；计价链路整体出问题也不该让用量接口报错。"""
    try:
        from core.llm.token_stats.pricing import ensure_catalog

        return await ensure_catalog(force=force)
    except Exception as exc:  # 降级：没有价就不显示钱，而不是整个接口失败
        logger.warning("价目表不可用，本次用量结果不计价: %s", exc)
        return None


@router.get("/overview", summary="LLM token 用量汇总")
async def token_stats_overview(
    granularity: str = Query("day", pattern="^(day|month)$", description="日 / 月粒度"),
    start: str = Query("", description="开始日期 YYYY-MM-DD（含）"),
    end: str = Query("", description="结束日期 YYYY-MM-DD（含）"),
    model: str = Query("", description="按模型精确筛选"),
    provider: str = Query("", description="按 provider 精确筛选"),
    top: int = Query(20, ge=1, le=100, description="分布表取前 N 项"),
):
    """返回总量、时间序列、模型 / 来源 / 渠道分布、成本与数据覆盖情况。"""
    try:
        from core.llm.token_stats import build_overview

        catalog = await _catalog_or_none()
        data = await asyncio.to_thread(
            lambda: build_overview(
                granularity=granularity,
                start=start,
                end=end,
                model=model,
                provider=provider,
                top=top,
                catalog=catalog,
            )
        )
        return success_response(data)
    except Exception as exc:  # 统计失败不能影响主业务
        logger.error("读取 token 用量统计失败: %s", exc, exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(exc))


@router.get("/pricing", summary="模型价目表状态与查询")
async def token_stats_pricing(
    keyword: str = Query("", description="按模型标识模糊查询价目条目"),
    limit: int = Query(30, ge=1, le=200, description="条目清单最多返回多少条"),
):
    """返回价目表健康度（同步时间、各来源成败、是否过期）与可搜索的条目。"""
    try:
        from core.llm.token_stats.pricing import get_pricing_config, pricing_status

        catalog = await _catalog_or_none()
        if catalog is None:
            return error_response(ErrorCode.INTERNAL_ERROR, message="价目表不可用")
        cfg = get_pricing_config()
        payload = pricing_status(catalog, cfg)
        payload["entries"] = [price.to_dict() for price in catalog.search(keyword, limit)]
        payload["keyword"] = keyword
        return success_response(payload)
    except Exception as exc:
        logger.error("读取价目表失败: %s", exc, exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(exc))


@router.post("/pricing/sync", summary="立刻重抓模型价目表")
async def token_stats_pricing_sync():
    """手动触发一轮抓取；抓失败仍回旧快照，不会把已有价格抹掉。"""
    try:
        from core.llm.token_stats.pricing import get_pricing_config, pricing_status

        catalog = await _catalog_or_none(force=True)
        if catalog is None:
            return error_response(ErrorCode.INTERNAL_ERROR, message="价目表同步失败")
        payload = pricing_status(catalog, get_pricing_config())
        failed = [name for name, st in (catalog.sources or {}).items() if st.get("ok") is False]
        message = "已同步" if not failed else f"部分来源失败: {', '.join(failed)}"
        return success_response(payload, message=message)
    except Exception as exc:
        logger.error("同步价目表失败: %s", exc, exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(exc))


@router.get("/dashboard", summary="token 用量看板页面")
async def token_stats_dashboard():
    """直接返回看板 HTML；页面内通过 /overview 拉数据。"""
    path = get_project_root() / DASHBOARD_REL_PATH
    if not path.exists():
        return error_response(
            ErrorCode.RESOURCE_NOT_FOUND,
            message=f"看板页面不存在: {path}",
        )
    return FileResponse(path)
