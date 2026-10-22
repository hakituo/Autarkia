# -*- coding: utf-8 -*-
"""Study Daily 学习日报域聚合路由。

本文件不再直接实现端点，而是作为业务子域的聚合入口（与 life.py 同构）：
- study_daily_content: 日报内容读取（日历 / 按日期读取 / 最新进度）
- study_daily_notes:   专题笔记读取
- study_daily_library: 学习库笔记（Study 根目录科目文件夹）
- study_daily_plan:    计划项写入（勾选 / 新增 / 编辑 / 删除，走计划真源）
- study_daily_version: 学习数据变更指纹（客户端进入页面时先做增量比对）
- study_daily_shared:  共享基建（日期校验 / 路径推导 / 文本读取），不挂路由

目录结构约定与各端点明细见对应子模块 docstring。
"""

from fastapi import APIRouter

from .study_daily_content import router as study_daily_content_router
from .study_daily_library import router as study_daily_library_router
from .study_daily_notes import router as study_daily_notes_router
from .study_daily_plan import router as study_daily_plan_router
from .study_daily_version import router as study_daily_version_router

router = APIRouter()

# 子路由自带 /study-daily 前缀，本聚合层绝不能再声明 prefix，
# 否则会叠加成 /study-daily/study-daily/*
router.include_router(study_daily_content_router)
router.include_router(study_daily_notes_router)
router.include_router(study_daily_library_router)
router.include_router(study_daily_plan_router)
router.include_router(study_daily_version_router)

__all__ = ["router"]
