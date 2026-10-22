# -*- coding: utf-8 -*-
"""加权记忆的关系图端点。

关系图本身由 :mod:`memory.core.relation_graph` 构建、:mod:`memory.core.graph_view`
裁剪成前端结构，本文件只做 HTTP 适配：

- ``GET /memories/{memory_id}/relations``：单条记忆的邻域，对应详情页「想起…」；
- ``GET /memories/anchors``：地标层（同一天 × 同一话题压成的片段），图谱首页；
- ``GET /memories/graph``：记忆网络子图，给定 ``seed_id`` 以它为中心，否则按显著度取种子。

始终返回有限大小的子图：全量记忆在手机上既画不动也看不懂，换种子等于在图里走一步。
"""

import asyncio
import time
from typing import Optional

from fastapi import APIRouter, Path, Query

from core.api.contract import error_response
from core.api.error_response import ErrorCode
from core.utils.logger import get_logger
from .memories import _wmm

logger = get_logger("MEMORY_GRAPH_ROUTER")

router = APIRouter(prefix="/memories", tags=["记忆系统"])


@router.get("/{memory_id}/relations", summary="获取某条记忆的关联邻域")
async def get_memory_relations(
    memory_id: str = Path(..., description="中心记忆 ID"),
    user_id: str = Query("default", description="用户 ID"),
    persona: Optional[str] = Query(None, description="人格文件名，传入后按角色隔离记忆"),
    limit: int = Query(12, ge=1, le=24, description="返回的邻居条数上限"),
    depth: int = Query(1, ge=1, le=2, description="向外扩散的跳数"),
    include_thinking: bool = Query(False, description="是否包含隐藏的 thinking 分类"),
):
    """返回中心记忆的邻居节点与边，按「跳数 → 边强度 → 权重」排序。"""
    from memory.core.graph_view import build_neighbor_view

    request_id = f"mem-rel-{memory_id}"
    try:
        manager = await asyncio.to_thread(_wmm, user_id, persona)
        view = await asyncio.to_thread(
            build_neighbor_view,
            manager,
            memory_id,
            limit=limit,
            max_depth=depth,
            include_thinking=include_thinking,
        )
        if view is None:
            return error_response(
                ErrorCode.RESOURCE_NOT_FOUND,
                message=f"记忆不存在: {memory_id}",
                request_id=request_id,
            )
        return {
            "status": "success",
            "data": view,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"获取记忆关联邻域失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


@router.get("/anchors", summary="获取记忆地标（图谱首页入口）")
async def get_memory_anchors(
    user_id: str = Query("default", description="用户 ID"),
    persona: Optional[str] = Query(None, description="人格文件名，传入后按角色隔离记忆"),
    limit: int = Query(12, ge=1, le=16, description="地标条数上限"),
    include_thinking: bool = Query(False, description="是否包含隐藏的 thinking 分类"),
):
    """把记忆压成「某天围绕某个话题的一簇」，作为图谱的入口层。"""
    from memory.core.graph_anchors import build_anchor_view

    try:
        manager = await asyncio.to_thread(_wmm, user_id, persona)
        anchors = await asyncio.to_thread(
            build_anchor_view,
            manager,
            limit=limit,
            include_thinking=include_thinking,
        )
        return {
            "status": "success",
            "data": {"anchors": anchors},
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"获取记忆地标失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


@router.get("/graph", summary="获取记忆网络子图")
async def get_memory_graph(
    user_id: str = Query("default", description="用户 ID"),
    persona: Optional[str] = Query(None, description="人格文件名，传入后按角色隔离记忆"),
    seed_id: Optional[str] = Query(None, description="中心记忆 ID；不传则按显著度自动取种子"),
    limit: int = Query(80, ge=2, le=120, description="子图节点数上限"),
    depth: int = Query(2, ge=1, le=3, description="从种子向外扩散的跳数"),
    include_thinking: bool = Query(False, description="是否包含隐藏的 thinking 分类"),
):
    """返回节点 + 边组成的子图；种子失效时返回空图而不是报错。"""
    from memory.core.graph_view import build_graph_view

    try:
        manager = await asyncio.to_thread(_wmm, user_id, persona)
        view = await asyncio.to_thread(
            build_graph_view,
            manager,
            seed_id=seed_id,
            limit=limit,
            max_depth=depth,
            include_thinking=include_thinking,
        )
        return {
            "status": "success",
            "data": view,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"获取记忆网络子图失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}
