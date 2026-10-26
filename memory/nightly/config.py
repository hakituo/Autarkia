from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from core.utils.logger import get_module_logger

logger = get_module_logger(__name__, "nightly_processor.log")


def _load_model_config() -> Dict[str, Any]:
    """加载模型路由配置。"""
    try:
        from config.model_config import load_model_config

        return load_model_config()
    except Exception as exc:
        logger.warning(f"加载模型路由配置失败: {exc}")
        return {}


def get_memory_distillation_model() -> Optional[str]:
    """获取记忆蒸馏模型配置。"""
    config = _load_model_config()
    memory_models = config.get("memory_models", {})
    return memory_models.get("distillation")


def get_nightly_model_routes() -> Dict[str, str]:
    """返回 nightly 使用的场景模型，便于启动时核对路由。"""
    try:
        from config.model_config import (
            get_character_daily_plan_model,
            get_journal_model,
        )

        return {
            "daily_summary": get_journal_model(),
            "user_plan": get_character_daily_plan_model(),
            "preference_merge": get_journal_model(),
            "distillation": get_memory_distillation_model() or "",
            "people_profiles": get_memory_distillation_model() or "",
        }
    except Exception as exc:
        logger.warning(f"读取 nightly 模型路由失败: {exc}")
        return {
            "daily_summary": "",
            "user_plan": "",
            "preference_merge": "",
            "distillation": get_memory_distillation_model() or "",
            "people_profiles": get_memory_distillation_model() or "",
        }


# 记忆蒸馏角色白名单：现在只在 Aveline 身上调参，调满意后再逐个放开。
# 不在名单里的 scope（其他角色、user / dual_role、legacy 人设留下的历史 scope）
# 一律不蒸馏——宁可空着，也不要拿别人的口吻去写一段记忆。
DEFAULT_DISTILLATION_ROLE_WHITELIST: tuple = ("aveline",)


def is_distillation_role_allowed(config: Dict[str, Any], role_id: str) -> bool:
    """当前 scope 的角色是否允许做记忆蒸馏。"""
    whitelist = config.get(
        "distillation_role_whitelist",
        DEFAULT_DISTILLATION_ROLE_WHITELIST,
    )
    return bool(role_id) and role_id in set(whitelist or ())


DEFAULT_NIGHTLY_CONFIG: Dict[str, Any] = {
    "enabled": True,
    # 夜间处理窗口：晚上 23:00 ~ 次日 12:00。
    # 之前 end_time=06:00，5 点兜底触发时受窗口限制只能 5~6 点生效，
    # 且服务器若在 6 点后（如早上 7 点开机）才启动则无法补跑昨天日记。
    # 结合 get_diary_target_date 的凌晨归属阈值 12（中午前归前一天），
    # 让兜底在整个上午都能安全地补生成"已结束前一天"的日记。
    "start_time": "23:00",
    "end_time": "12:00",
    "weight_increment": 1.0,
    "min_frequency": 3,
    "auto_run": True,
    "max_topics_to_update": 10,
    "distillation_enabled": True,
    # 只对这些角色做记忆蒸馏；改这里（或传 config 覆盖）即可逐个放开
    "distillation_role_whitelist": list(DEFAULT_DISTILLATION_ROLE_WHITELIST),
    "distillation_threshold_hours": 1,
    # 单轮预算（v3 F4）：不再有 24h 资格窗口，积压按最旧优先跨多晚消费完
    "max_distill_per_night": 50,
    "max_distill_chars_per_night": 60000,
    "max_distill_seconds_per_night": 900,
    # 失败条目按指数退避重试，达到次数后在账本里单列 exhausted 等人工处理
    "distillation_max_attempts": 3,
    # 批量蒸馏：每批合并的待蒸馏条数（合并为一次 LLM 请求，降低请求数并提升前缀命中）
    "distillation_batch_size": 10,
    # 按时间连续性分组：相邻待蒸馏消息间隔超过该分钟数视为不同对话段，拆开各自蒸馏
    "distillation_group_gap_minutes": 30,
    # 按 segment 提取（v3 F3）：默认关；打开后先影子写派生笔记库，不影响任何读路径
    "segment_extraction_enabled": False,
    "segment_extraction_shadow": True,
    # 分段参数：待 C8 定（实验用 16 条消息≈8 轮 / 空闲 30 分钟 / 4000 字封口）
    "segment_idle_seconds": 1800,
    "segment_max_turns": 8,
    "segment_max_chars": 4000,
    # 按段作业单轮预算：段数 / 正文字符 / 墙钟秒数，0 表示不设该项上限
    "segment_max_per_night": 30,
    "segment_max_chars_per_night": 60000,
    "segment_max_seconds_per_night": 600,
    "segment_max_attempts": 3,
}

# `__file__` 位于 `memory/nightly/config.py`，向上两级回到项目根目录。
ANALYSIS_DIR = Path(__file__).resolve().parents[2] / "history" / "analysis"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
