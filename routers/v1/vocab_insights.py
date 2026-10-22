# -*- coding: utf-8 -*-
"""背单词学习洞察接口：今日已背、词书进度、已学单词。

与 ``routers/v1/vocab.py`` 共用 ``/vocab`` 前缀，但单独成文件：
那边是「开始背 / 提交评分」的核心链路，这里只做只读展示，
避免核心复习文件继续膨胀。
"""

import time

from fastapi import APIRouter, Query

from core.api.contract import error_response
from core.api.error_response import ErrorCode
from core.utils.logger import get_logger

logger = get_logger("VOCAB_INSIGHTS_ROUTER")

router = APIRouter(prefix="/vocab", tags=["背单词"])


def _get_study_service():
    """延迟导入，避免启动时加载 tkinter/matplotlib 等重型依赖。"""
    from core.services.study.service import get_study_service

    return get_study_service()


@router.get("/today-words", summary="获取今日已背单词明细")
async def get_today_words(
    date: str = Query("", description="日期 YYYY-MM-DD；留空取今天"),
):
    """按词汇总今天的评分：新学 / 复习、评分次数、末次评分与时间。"""
    try:
        service = _get_study_service()
        data = service.get_today_words(date)
        return {"status": "success", "data": data, "timestamp": time.time()}
    except Exception as e:
        logger.error(f"Failed to get today words: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.get("/book-progress", summary="获取当前词书学习进度")
async def get_book_progress():
    """当前词书的已学 / 未学 / 掌握 / 待复习与完成百分比。"""
    try:
        service = _get_study_service()
        data = service.get_book_progress()
        return {"status": "success", "data": data, "timestamp": time.time()}
    except Exception as e:
        logger.error(f"Failed to get book progress: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.get("/learned-words", summary="分页获取已学单词")
async def get_learned_words(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    status: str = Query("all", description="all / mastered / learning / due"),
    scope: str = Query("book", description="book=仅当前词书；all=全部进度"),
):
    """已学单词列表，按最近复习时间倒序；供「已学单词」浏览页使用。"""
    try:
        service = _get_study_service()
        data = service.get_learned_words(
            page=page, page_size=page_size, status=status, scope=scope
        )
        return {"status": "success", "data": data, "timestamp": time.time()}
    except Exception as e:
        logger.error(f"Failed to get learned words: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))
