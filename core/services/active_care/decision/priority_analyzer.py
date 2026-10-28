"""优先级分析模块
负责分析任务优先级、每日推送优先级

重构后：
- 每日推送优先级函数委托到 daily_push_priority 模块
- PriorityAnalyzer 保留核心优先级焦点构建和探测签名/冷却逻辑
"""

from typing import Any, Dict, List, Optional

from core.utils.logger import get_module_logger
from config.integrated_config import get_settings
from core.services.priority import cooldown_seconds_for_focus
from core.services.active_care.decision.daily_push_priority import (
    build_daily_push_priority_candidates,
    analyze_daily_push_priority as _analyze_daily_push_priority,
    persist_daily_push_priority_analysis as _persist_daily_push_priority_analysis,
)

logger = get_module_logger("ACTIVE_CARE_PRIORITY", "active_care_schedule.log")


class PriorityAnalyzer:
    """优先级分析器，负责构建和分析主动关怀的优先级队列"""
    
    def __init__(self, bert_analyzer=None):
        self.settings = get_settings()
        self.bert_analyzer = bert_analyzer
    
    def build_priority_focus(
        self,
        workspace_snapshot: Dict[str, Any],
        now_dt,
        recent_history: Optional[List[Dict[str, Any]]] = None,
        elapsed_seconds: int = 0,
    ) -> Dict[str, Any]:
        """
        构建优先级焦点，决定当前应该关注什么

        Args:
            workspace_snapshot: 工作区快照
            now_dt: 当前时间
            recent_history: 最近聊天记录
            elapsed_seconds: 用户沉默时长（秒），保留参数以兼容调用方

        Returns:
            {
                "must_probe": bool,  # 是否必须探测
                "stage": str,        # 当前阶段
                "task_probe": dict,  # 任务探测信息
                "portrait_priority": list,  # 恒为空（画像补齐已移除）
                "covered_topics": list,     # 恒为空
                "summary": dict,            # 摘要
            }
        """
        snapshot = workspace_snapshot if isinstance(workspace_snapshot, dict) else {}
        daily_tasks = snapshot.get("daily_tasks") or {}
        task_focus = daily_tasks.get("focus") or {}
        task_probe = {}
        stage = "idle"
        must_probe = False

        due_soon = task_focus.get("timed_due_soon") or []
        overdue = task_focus.get("timed_overdue") or []
        timed_pending = int(task_focus.get("timed_pending") or 0)
        untimed_pending = int(task_focus.get("untimed_pending") or 0)

        chosen_task = None
        task_reason = ""
        if overdue:
            chosen_task = overdue[0]
            task_reason = "overdue"
            stage = "task_follow_up"
            must_probe = True
        elif due_soon:
            chosen_task = due_soon[0]
            task_reason = "due_soon"
            stage = "task_follow_up"
            must_probe = True
        else:
            timed = daily_tasks.get("timed") or []
            untimed = daily_tasks.get("untimed") or []
            pending_timed = [
                item for item in timed if str(item.get("status", "pending")) == "pending"
            ]
            pending_untimed = [
                item for item in untimed if str(item.get("status", "pending")) == "pending"
            ]
            if pending_timed:
                chosen_task = pending_timed[0]
                task_reason = "timed_pending"
            elif pending_untimed:
                chosen_task = pending_untimed[0]
                task_reason = "untimed_pending"
            if chosen_task and now_dt.hour >= 9:
                stage = "task_follow_up"
                must_probe = True

        if chosen_task:
            task_probe = {
                "reason": task_reason,
                "task_id": str(chosen_task.get("id") or "").strip(),
                "task_title": str(chosen_task.get("title") or "").strip(),
                "minutes_to_execution": chosen_task.get("minutes_to_execution"),
                "pending_total": timed_pending + untimed_pending,
            }

        # 画像补齐（每天按时段追问起床 / 吃饭 / 活动等）已于 2026-10-28 移除：
        # 它是查岗式主动消息的主要来源。键保留为空，供只读它的下游（决策引擎
        # 状态压缩、冷却档位）保持兼容。
        return {
            "must_probe": must_probe,
            "stage": stage,
            "task_probe": task_probe,
            "portrait_priority": [],
            "covered_topics": [],
            "summary": {
                "timed_pending": timed_pending,
                "untimed_pending": untimed_pending,
            },
        }

    def get_priority_probe_signature(self, focus: Dict[str, Any]) -> str:
        """获取优先级探测签名，用于去重"""
        if not isinstance(focus, dict):
            return "none"
        task_probe = focus.get("task_probe") or {}
        if task_probe:
            return (
                f"task:{task_probe.get('reason')}:{task_probe.get('task_id') or ''}:"
                f"{task_probe.get('task_title') or ''}"
            )
        return str(focus.get("stage") or "idle")

    def get_priority_probe_cooldown_seconds(self, focus: Dict[str, Any]) -> int:
        """获取优先级探测冷却时间。

        2026-10-02 起委托给共用优先级词汇 `core.services.priority`：
        冷却秒数按「档位」定义在一处（overdue 20min / due_soon 15min /
        pending 45min / routine 90min / 默认 3600），不再在这里散落硬编码。
        """
        return cooldown_seconds_for_focus(focus)

    # ── 以下方法委托到 daily_push_priority 模块 ──

    def build_daily_push_priority_candidates(
        self,
        *,
        workspace_snapshot: Dict[str, Any],
        priority_focus: Dict[str, Any],
        urgent_needs: List[str],
    ) -> List[Dict[str, Any]]:
        """构建每日推送优先级候选列表（委托到 daily_push_priority 模块）"""
        return build_daily_push_priority_candidates(
            workspace_snapshot=workspace_snapshot,
            priority_focus=priority_focus,
            urgent_needs=urgent_needs,
        )

    async def analyze_daily_push_priority(
        self,
        *,
        now: float,
        now_dt,
        latest_user_signal_ts: float,
        workspace_snapshot: Dict[str, Any],
        priority_focus: Dict[str, Any],
        urgent_needs: List[str],
        state_data: Dict[str, Any],
        recent_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """分析每日推送优先级（委托到 daily_push_priority 模块）"""
        return await _analyze_daily_push_priority(
            now=now,
            now_dt=now_dt,
            latest_user_signal_ts=latest_user_signal_ts,
            workspace_snapshot=workspace_snapshot,
            priority_focus=priority_focus,
            urgent_needs=urgent_needs,
            state_data=state_data,
            recent_history=recent_history,
        )

    async def persist_daily_push_priority_analysis(
        self,
        *,
        now_dt,
        analysis: Dict[str, Any],
        workspace_snapshot: Dict[str, Any],
        priority_focus: Dict[str, Any],
        runtime_scope: str,
    ) -> None:
        """持久化每日推送优先级分析结果（委托到 daily_push_priority 模块）"""
        await _persist_daily_push_priority_analysis(
            now_dt=now_dt,
            analysis=analysis,
            workspace_snapshot=workspace_snapshot,
            priority_focus=priority_focus,
            runtime_scope=runtime_scope,
        )
