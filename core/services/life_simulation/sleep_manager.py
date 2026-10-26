"""角色睡眠管理器（薄壳门面）。

职责收敛为三件事：
1. 生命周期与持久化（构造、模板重载、状态文件读写）
2. 对外只读 API（`get_state` / `get_summary` / `get_prompt_summary`）
3. 运行时隔离：睡眠模块内部异常在这里兜住并降级，绝不外溢到聊天回复、
   状态展示与主动关怀决策

具体实现按职责拆在 `sleep/` 子包：
- `sleep.windows`：时间窗口纯函数（无状态、无 IO）
- `sleep.transitions`：状态推进
- `sleep.metrics`：睡眠指标与噩梦
- `sleep.triggers`：入睡 / 起床的上游事件
- `sleep.recovery`：被叫醒后的恢复决策
- `sleep.events`：外部事件写入与活动覆盖
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

from core.services.character_daily.config import (
    CharacterDailyConfig,
    RoleScheduleTemplate,
    SleepProfileConfig,
    load_character_daily_config,
    load_schedule_templates,
)
from core.services.character_daily.role_names import ROLE_NAMES as _ROLE_NAMES
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

from .sleep import windows as _windows
from .sleep.events import SleepEventsMixin
from .sleep.metrics import SleepMetricsMixin
from .sleep.recovery import SleepRecoveryMixin
from .sleep.transitions import SleepTransitionsMixin
from .sleep.triggers import SleepTriggersMixin
from .sleep.windows import SleepWindowsMixin
from .sleep.windows import (  # noqa: F401 - 兼容旧的模块级私有导入
    minutes_to_hhmm as _minutes_to_hhmm,
    parse_hhmm_to_minutes as _parse_hhmm_to_minutes,
)
from .sleep_models import SleepPhase, SleepRuntimeState
from .sleep_state_store import SleepStateStore

# 必须用 get_logger，否则日志只走 root logger（仅 console handler），不写入 autarkia_main.log，
# 导致 _on_enter_sleeping / _on_enter_waking_up 的触发记录无法通过日志文件验证
logger = get_logger(__name__)

# 睡眠状态读取异常的日志限流间隔（秒）：避免异常期间刷爆日志文件。
_ERROR_LOG_INTERVAL_SECONDS = 300.0

# 兼容旧引用：常量在子模块里维护，这里保留同名入口
_MAX_SANE_SLEEP_SECONDS = _windows.MAX_SANE_SLEEP_SECONDS
_WAKING_UP_OVERRIDE_WINDOW_SECONDS = 20 * 60


class SleepManager(
    SleepWindowsMixin,
    SleepTransitionsMixin,
    SleepMetricsMixin,
    SleepTriggersMixin,
    SleepRecoveryMixin,
    SleepEventsMixin,
):
    """统一管理角色睡眠状态。"""

    def __init__(self, store: Optional[SleepStateStore] = None):
        self._store = store or SleepStateStore()
        self._templates: Dict[str, RoleScheduleTemplate] = load_schedule_templates()
        self._runtime_config: CharacterDailyConfig = load_character_daily_config()
        self._states: Dict[str, SleepRuntimeState] = self._store.load()
        # 运行时报错限流：同一角色同一类错误每 _ERROR_LOG_INTERVAL_SECONDS 只打一次
        self._error_log_ts: Dict[str, float] = {}

    def reload_templates(self) -> None:
        """重载角色配置。"""
        self._templates = load_schedule_templates()
        self._runtime_config = load_character_daily_config()

    def _log_runtime_error(self, role_id: str, where: str, exc: BaseException) -> None:
        """限流记录睡眠状态读取异常。"""
        key = f"{role_id}:{where}"
        now = time.time()
        if now - self._error_log_ts.get(key, 0.0) < _ERROR_LOG_INTERVAL_SECONDS:
            return
        self._error_log_ts[key] = now
        logger.error(
            "睡眠状态读取异常（%s, role=%s），已降级沿用上次状态: %s",
            where,
            role_id,
            exc,
            exc_info=True,
        )

    def _fallback_state(self, role_id: str, now: Optional[datetime] = None) -> SleepRuntimeState:
        """异常降级：返回上次可用状态；没有就返回一个中性空状态。"""
        role_key = str(role_id or "").strip().lower()
        state = self._states.get(role_key)
        if state is not None:
            return state
        dt = now or get_current_time()
        state = SleepRuntimeState(role_id=role_key, date=dt.strftime("%Y-%m-%d"))
        self._states[role_key] = state
        return state

    def get_state(self, role_id: str, now: Optional[datetime] = None) -> SleepRuntimeState:
        """获取并刷新角色睡眠状态。

        运行时隔离：睡眠模块内部异常（时区不一致、状态文件损坏等）必须在这里
        兜住，不能扩散到聊天回复、状态展示与主动关怀决策——否则一个睡眠异常
        就能让角色既不回消息、状态又停在旧活动上。
        """
        try:
            state = self._ensure_role_state(role_id, now=now)
            self._update_runtime_state(role_id, state, now=now)
            return state
        except Exception as exc:  # noqa: BLE001 - 边界隔离，禁止异常外溢
            self._log_runtime_error(role_id, "get_state", exc)
            return self._fallback_state(role_id, now=now)

    def get_all_states(self, now: Optional[datetime] = None) -> Dict[str, Dict[str, Any]]:
        """获取所有角色的睡眠状态摘要。"""
        result: Dict[str, Dict[str, Any]] = {}
        for role_id in self._templates.keys():
            result[role_id] = self.get_summary(role_id, now=now)
        return result

    def mark_nightly_done(self, role_id: str, date_str: str) -> None:
        """标记某角色当日 nightly 已完成。"""
        state = self.get_state(role_id)
        state.nightly_done_for_date = str(date_str or "")
        self._persist()

    def get_summary(self, role_id: str, now: Optional[datetime] = None) -> Dict[str, Any]:
        """获取供其他模块使用的摘要状态（异常时返回中性摘要，不外抛）。"""
        try:
            dt = now or get_current_time()
            state = self.get_state(role_id, now=dt)
            next_wake_dt = self._resolve_next_wake_dt(role_id, dt)
            profile = self._get_profile(role_id)
            minutes_until_wakeup = int((next_wake_dt - dt).total_seconds() / 60)
            return {
                "role_id": role_id,
                "role_name": _ROLE_NAMES.get(role_id, role_id),
                "date": state.date,
                "phase": state.phase.value,
                "is_sleeping": state.is_sleeping,
                "planned_sleep_time": state.planned_sleep_time,
                "planned_wake_time": state.planned_wake_time,
                "last_sleep_duration_hours": round(state.last_sleep_duration_hours, 2),
                "current_sleep_duration_hours": round(state.current_sleep_duration_hours, 2),
                "sleep_debt_hours": round(state.sleep_debt_hours, 2),
                "sleep_quality_score": round(state.sleep_quality_score, 1),
                "sleep_inertia_score": round(state.sleep_inertia_score, 1),
                "nightmare_level": state.nightmare_level,
                "impact_level": state.impact_level,
                "night_wake_count": state.night_wake_count,
                "overslept": state.overslept,
                "stay_up_activity": state.stay_up_activity,
                "minutes_until_wakeup": minutes_until_wakeup,
                "patch_pending": state.patch_pending,
                "silence_window_seconds": int(profile.silence_window_seconds),
                "last_wake_ts": float(state.last_wake_ts or 0.0),
                "last_chat_ts": float(state.last_chat_ts or 0.0),
                "actual_wakeup_ts": float(state.actual_wakeup_ts or 0.0),
            }
        except Exception as exc:  # noqa: BLE001 - 边界隔离，禁止异常外溢
            self._log_runtime_error(role_id, "get_summary", exc)
            return self._fallback_summary(role_id, now=now)

    def _fallback_summary(
        self, role_id: str, now: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """异常降级用的中性摘要：字段齐全，语义为「状态未知」。"""
        state = self._states.get(str(role_id or "").strip().lower())
        return {
            "role_id": role_id,
            "role_name": _ROLE_NAMES.get(role_id, role_id),
            "date": state.date if state is not None else "",
            "phase": state.phase.value if state is not None else "unknown",
            "is_sleeping": bool(state.is_sleeping) if state is not None else False,
            "planned_sleep_time": state.planned_sleep_time if state is not None else "",
            "planned_wake_time": state.planned_wake_time if state is not None else "",
            "last_sleep_duration_hours": 0.0,
            "current_sleep_duration_hours": 0.0,
            "sleep_debt_hours": 0.0,
            "sleep_quality_score": 0.0,
            "sleep_inertia_score": 0.0,
            "nightmare_level": "none",
            "impact_level": "none",
            "night_wake_count": 0,
            "overslept": False,
            "stay_up_activity": "",
            "minutes_until_wakeup": 0,
            "patch_pending": False,
            "silence_window_seconds": 180,
            "last_wake_ts": 0.0,
            "last_chat_ts": 0.0,
            "actual_wakeup_ts": 0.0,
        }

    def get_prompt_summary(self, role_id: str, now: Optional[datetime] = None) -> str:
        """构建简洁的睡眠摘要文本。"""
        summary = self.get_summary(role_id, now=now)
        lines = [
            f"{summary['role_name']}当前睡眠状态：{summary['phase']}",
            f"计划作息：{summary['planned_sleep_time']}睡，{summary['planned_wake_time']}起",
        ]
        if summary["is_sleeping"]:
            lines.append("现在处于睡眠中。")
        if summary["night_wake_count"] > 0:
            lines.append(f"今夜被吵醒 {summary['night_wake_count']} 次。")
        if summary["sleep_debt_hours"] > 0.3:
            lines.append(f"睡眠债约 {summary['sleep_debt_hours']:.1f} 小时。")
        if summary["sleep_inertia_score"] > 0.1:
            lines.append(f"睡眠惯性偏强（{summary['sleep_inertia_score']:.1f}/100）。")
        if summary["nightmare_level"] != "none":
            lines.append(f"噩梦/睡眠质量问题等级：{summary['nightmare_level']}。")
        if summary["impact_level"] != "none":
            lines.append(f"今日状态影响等级：{summary['impact_level']}。")
        if summary["stay_up_activity"] and summary["phase"] in (
            SleepPhase.STAY_UP_LATE.value,
            SleepPhase.SLEEP_LATER.value,
        ):
            lines.append(f"当前偏向在深夜做：{summary['stay_up_activity']}。")
        return "\n".join(lines)

    def _ensure_role_state(self, role_id: str, now: Optional[datetime] = None) -> SleepRuntimeState:
        role_id = str(role_id or "").strip().lower()
        if role_id in self._states:
            return self._states[role_id]
        dt = now or get_current_time()
        state = SleepRuntimeState(role_id=role_id, date=dt.strftime("%Y-%m-%d"))
        self._states[role_id] = state
        return state

    def _get_profile(self, role_id: str) -> SleepProfileConfig:
        template = self._templates.get(role_id)
        if template and template.sleep_profile:
            return template.sleep_profile
        return SleepProfileConfig()

    def _persist(self) -> None:
        self._store.save(self._states)


_sleep_manager_instance: Optional[SleepManager] = None
_sleep_manager_lock = threading.Lock()


def get_sleep_manager() -> SleepManager:
    """获取全局睡眠管理器。"""
    global _sleep_manager_instance
    if _sleep_manager_instance is None:
        with _sleep_manager_lock:
            if _sleep_manager_instance is None:
                _sleep_manager_instance = SleepManager()
    return _sleep_manager_instance
