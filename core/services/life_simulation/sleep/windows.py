"""睡眠时间窗口的纯计算。

不持有状态、不读文件、不发消息：输入全部显式传入，方便单测与跨模块复用。
`SleepManager` 通过 `SleepWindowsMixin` 保留原有的私有方法名，
行为与本模块的纯函数一一对应。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from core.services.character_daily.config import SleepProfileConfig

from ..sleep_models import SleepRuntimeState

# 单次睡眠的合理上限：超过一昼夜说明睡眠起点被旧状态污染，不能按锁定窗口补算时长。
MAX_SANE_SLEEP_SECONDS = 24 * 3600

# 锁定窗口与当前时刻允许的最大偏离：超过说明状态文件是别的日期留下的，
# 继续认这条锁会让角色永久停在 sleeping（验证脚本用固定日期跑过就会这样）。
MAX_LOCK_DRIFT_SECONDS = 3 * 24 * 3600

_MINUTES_PER_DAY = 24 * 60


def parse_hhmm_to_minutes(value: str, fallback: int) -> int:
    """把 "HH:MM" 解析成当天分钟数，失败时返回 fallback。"""
    try:
        hour_str, minute_str = str(value or "").split(":")
        hour = max(0, min(23, int(hour_str)))
        minute = max(0, min(59, int(minute_str)))
        return hour * 60 + minute
    except Exception:
        return fallback


def minutes_to_hhmm(total_minutes: int) -> str:
    """把当天分钟数格式化成 "HH:MM"。"""
    total_minutes %= _MINUTES_PER_DAY
    hour = total_minutes // 60
    minute = total_minutes % 60
    return f"{hour:02d}:{minute:02d}"


def weekday_offset_minutes(profile: SleepProfileConfig, now: datetime) -> int:
    """工作日按睡眠惯性、休息日按赖床倾向，给起床时间加一点偏移。"""
    if now.weekday() >= 5:
        return int(profile.oversleep_tendency * 25)
    return int(profile.sleep_inertia_tendency * 8)


def rest_day_sleep_offset(profile: SleepProfileConfig, now: datetime) -> int:
    """休息日按夜猫子倾向顺延入睡时间。"""
    if now.weekday() < 5:
        return 0
    return int(profile.night_owl_tendency * 30)


def planned_minutes(
    profile: SleepProfileConfig,
    now: datetime,
    *,
    fallback_sleep: int,
    fallback_wake: int,
) -> tuple[int, int]:
    """解析角色在指定日期应使用的计划睡眠/起床分钟数。"""
    is_weekend = now.weekday() >= 5
    wake_time = profile.weekend_wake_time if is_weekend else profile.weekday_wake_time
    sleep_time = profile.weekend_sleep_time if is_weekend else profile.weekday_sleep_time
    sleep_minutes = parse_hhmm_to_minutes(sleep_time, fallback_sleep)
    wake_minutes = parse_hhmm_to_minutes(wake_time, fallback_wake)
    wake_minutes += weekday_offset_minutes(profile, now)
    sleep_minutes += rest_day_sleep_offset(profile, now)

    wake_minutes = max(0, min(_MINUTES_PER_DAY - 1, wake_minutes))
    sleep_minutes = max(0, min(_MINUTES_PER_DAY - 1, sleep_minutes))
    return sleep_minutes, wake_minutes


def build_sleep_window(
    base_day_start: datetime,
    sleep_minutes: int,
    wake_minutes: int,
) -> tuple[datetime, datetime]:
    """根据某天的作息配置构造单个睡眠窗口。"""
    sleep_dt = base_day_start + timedelta(minutes=sleep_minutes)
    wake_dt = base_day_start + timedelta(minutes=wake_minutes)
    if wake_dt <= sleep_dt:
        wake_dt += timedelta(days=1)
    return sleep_dt, wake_dt


def resolve_sleep_window(
    now: datetime,
    sleep_minutes: int,
    wake_minutes: int,
) -> tuple[datetime, datetime]:
    """取当前时刻所属的睡眠窗口；落在白天时返回最近一个已结束的窗口。"""
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    candidate_windows = [
        build_sleep_window(day_start - timedelta(days=1), sleep_minutes, wake_minutes),
        build_sleep_window(day_start, sleep_minutes, wake_minutes),
        build_sleep_window(day_start + timedelta(days=1), sleep_minutes, wake_minutes),
    ]

    for sleep_dt, wake_dt in candidate_windows:
        if sleep_dt <= now < wake_dt:
            return sleep_dt, wake_dt

    ended_windows = [window for window in candidate_windows if window[1] <= now]
    if ended_windows:
        return max(ended_windows, key=lambda item: item[1])

    return min(candidate_windows, key=lambda item: item[0])


def resolve_next_wake_dt(
    now: datetime,
    sleep_minutes: int,
    wake_minutes: int,
) -> datetime:
    """获取从当前时刻开始的下一次计划起床时间。"""
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    candidate_windows = [
        build_sleep_window(day_start - timedelta(days=1), sleep_minutes, wake_minutes),
        build_sleep_window(day_start, sleep_minutes, wake_minutes),
        build_sleep_window(day_start + timedelta(days=1), sleep_minutes, wake_minutes),
        build_sleep_window(day_start + timedelta(days=2), sleep_minutes, wake_minutes),
    ]
    future_wakes = [wake_dt for _, wake_dt in candidate_windows if wake_dt > now]
    if future_wakes:
        return min(future_wakes)
    return max(wake_dt for _, wake_dt in candidate_windows)


def resolve_effective_sleep_start_ts(
    state: SleepRuntimeState,
    *,
    sleep_dt: datetime,
    wake_dt: datetime,
) -> float:
    """纠正被旧状态污染的睡眠起点，避免白天补算出几十小时睡眠。"""
    planned_sleep_ts = sleep_dt.timestamp()
    planned_wake_ts = wake_dt.timestamp()
    recorded_sleep_ts = float(state.actual_sleep_start_ts or 0.0)
    if recorded_sleep_ts <= 0:
        return planned_sleep_ts
    if recorded_sleep_ts < planned_sleep_ts:
        return planned_sleep_ts
    if recorded_sleep_ts > planned_wake_ts:
        return planned_sleep_ts
    return recorded_sleep_ts


def apply_locked_sleep_window(
    state: SleepRuntimeState,
    sleep_dt: datetime,
    wake_dt: datetime,
    now: Optional[datetime] = None,
) -> tuple[datetime, datetime]:
    """睡眠中一律使用入睡时锁定的窗口。

    跨天会切到另一套作息档（如工作日 23:00 睡、休息日 00:00 睡），同一夜在
    00:00 前后会被 `resolve_sleep_window` 算成两个不同窗口：00:00 时今日窗口
    还没开始，只能回退到昨夜已结束的窗口，于是 `dt >= wake_dt` 误判「按作息
    起床」发早安；00:10 今日窗口开始，又判定「该睡了」再发一次晚安。
    锁定后整夜只认入睡那次窗口，起床时刻不再随跨天重算。
    """
    if not state.is_sleeping:
        return sleep_dt, wake_dt
    locked_wake_ts = float(state.sleep_window_wake_ts or 0.0)
    if locked_wake_ts <= 0:
        return sleep_dt, wake_dt
    # 锁来自别的日期（例如验证脚本用固定日期跑过、状态文件被写脏）时不再认，
    # 否则角色会被一条早已不属于今天的锁永久按在 sleeping 里。
    if now is not None:
        drift = abs(locked_wake_ts - now.timestamp())
        if drift > MAX_LOCK_DRIFT_SECONDS:
            return sleep_dt, wake_dt
    # 必须按窗口自带的 tzinfo 还原：get_current_time() 返回的是带时区的时间，
    # 裸 datetime.fromtimestamp() 得到 naive datetime，和 dt 一比就抛
    # 「can't compare offset-naive and offset-aware datetimes」。
    tzinfo = sleep_dt.tzinfo
    locked_wake_dt = datetime.fromtimestamp(locked_wake_ts, tz=tzinfo)
    sleep_start_ts = float(state.actual_sleep_start_ts or 0.0)
    locked_sleep_dt = (
        datetime.fromtimestamp(sleep_start_ts, tz=tzinfo)
        if sleep_start_ts > 0
        else sleep_dt
    )
    if locked_sleep_dt >= locked_wake_dt:
        return sleep_dt, wake_dt
    # 睡眠起点被旧状态污染（超过一昼夜）时不信锁定值，交回原有补算逻辑纠正
    if (locked_wake_dt - locked_sleep_dt).total_seconds() > MAX_SANE_SLEEP_SECONDS:
        return sleep_dt, wake_dt
    return locked_sleep_dt, locked_wake_dt


class SleepWindowsMixin:
    """把纯函数包装成 manager 的既有私有方法（保持内部接口不变）。"""

    def _get_planned_minutes(self, role_id: str, now: datetime) -> tuple[int, int]:
        """解析角色在指定日期应使用的计划睡眠/起床分钟数。"""
        template = self._templates.get(role_id)
        return planned_minutes(
            self._get_profile(role_id),
            now,
            fallback_sleep=parse_hhmm_to_minutes(
                getattr(template, "sleep_time", "23:00"), 23 * 60
            ),
            fallback_wake=parse_hhmm_to_minutes(
                getattr(template, "wake_time", "07:00"), 7 * 60
            ),
        )

    def _resolve_sleep_window(
        self, role_id: str, now: datetime
    ) -> tuple[datetime, datetime]:
        sleep_minutes, wake_minutes = self._get_planned_minutes(role_id, now)
        return resolve_sleep_window(now, sleep_minutes, wake_minutes)

    def _resolve_next_wake_dt(self, role_id: str, now: datetime) -> datetime:
        """获取从当前时刻开始的下一次计划起床时间。"""
        sleep_minutes, wake_minutes = self._get_planned_minutes(role_id, now)
        return resolve_next_wake_dt(now, sleep_minutes, wake_minutes)

    @staticmethod
    def _build_sleep_window(
        base_day_start: datetime,
        sleep_minutes: int,
        wake_minutes: int,
    ) -> tuple[datetime, datetime]:
        """根据某天的作息配置构造单个睡眠窗口。"""
        return build_sleep_window(base_day_start, sleep_minutes, wake_minutes)

    def _apply_locked_sleep_window(
        self,
        state: SleepRuntimeState,
        sleep_dt: datetime,
        wake_dt: datetime,
        now: Optional[datetime] = None,
    ) -> tuple[datetime, datetime]:
        """睡眠中一律使用入睡时锁定的窗口。"""
        return apply_locked_sleep_window(state, sleep_dt, wake_dt, now=now)

    def _resolve_effective_sleep_start_ts(
        self,
        state: SleepRuntimeState,
        *,
        sleep_dt: datetime,
        wake_dt: datetime,
    ) -> float:
        """纠正被旧状态污染的睡眠起点。"""
        return resolve_effective_sleep_start_ts(
            state, sleep_dt=sleep_dt, wake_dt=wake_dt
        )
