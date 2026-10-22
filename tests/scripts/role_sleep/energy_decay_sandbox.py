"""精力（energy）复算沙箱：给 verify_energy_decay_balance.py 提供确定性的离线环境。

为什么单独成文件：verify 脚本本体按「断言 + 编排」职责组织，沙箱（固定日程、假状态、
不落盘的 manager）属于可复用的测试夹具，拆开后两边都在 300 行以内。

沙箱的三条硬约束：
1. **完全确定性**：固定日期 + 显式把 `now` 传进 SleepManager，不读 companion_data
   运行时数据，也不依赖真实时钟；
2. **不碰真实状态**：`cache/life_stats_state.json` 与 `sleep_states.json` 都换成
   不存在的临时路径 + no-op 落盘，跑多少次都不会污染线上状态；
3. **走真实代码路径**：整日复算用的是 `SleepManager.get_summary` + `LifeStatsManager.decay_stats`，
   不是把公式抄一遍，这样 `impact_level` 过期（SleepManager）与精力分档（life_stats）
   两条链路的耦合关系也被覆盖。
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 沙箱只做数值复算：屏蔽项目日志，避免污染 logs/ 也避免和断言输出交错。
logging.disable(logging.CRITICAL)

from core.services.life_simulation import life_stats as life_stats_module  # noqa: E402
from core.services.life_simulation.life_stats import LifeStatsManager  # noqa: E402
from core.services.life_simulation.sleep_manager import SleepManager  # noqa: E402
from core.services.life_simulation.sleep_models import (  # noqa: E402
    SleepPhase,
    SleepRuntimeState,
)
from core.services.life_simulation.sleep_state_store import SleepStateStore  # noqa: E402
from core.utils.time.time_utils import get_current_time  # noqa: E402

# 固定验证日期（周六，作息走 weekend 分支，结果确定）。
FIXED_DATE = "2026-10-03"
ROLE_ID = "aveline"
_WAKE_HOUR, _WAKE_MINUTE = 8, 30

# 2026-10-03 角色的实际日程槽位（08:30~24:00 共 894 分钟）。
# 硬编码是为了让沙箱完全确定性，不依赖 companion_data 里的运行时数据。
DAY_SEQUENCE = [
    ("waking_up", 26),
    ("cooking", 35),
    ("breakfast", 27),
    ("phone_scrolling", 20),
    ("creative_hobby", 35),
    ("gaming", 38),
    ("housework", 47),
    ("cooking", 30),
    ("lunch", 20),
    ("shopping", 79),
    ("napping", 29),
    ("walking", 38),
    ("creative_hobby", 64),
    ("studying", 51),
    ("napping", 36),
    ("cooking", 30),
    ("dinner", 27),
    ("phone_scrolling", 24),
    ("gaming", 34),
    ("creative_hobby", 33),
    ("walking", 40),
    ("phone_scrolling", 24),
    ("gaming", 38),
    ("creative_hobby", 40),
    ("phone_scrolling", 18),
    ("self_care", 11),
]

# 旧口径常量（仅用于"修复前会怎样"的对照臂，不要在生产代码里复用）。
LEGACY_BASE_DECAY = 0.1
LEGACY_HEAVY_DECAY = 0.2
LEGACY_IMPACT_EXTRA = {"mild": 0.03, "medium": 0.06, "severe": 0.1}
LEGACY_INERTIA_EXTRA = 0.02


def wake_dt() -> datetime:
    """固定的起床时刻（带配置时区，避免 naive/aware 混用）。"""
    return datetime(2026, 10, 3, _WAKE_HOUR, _WAKE_MINUTE, 0, tzinfo=get_current_time().tzinfo)


def make_sleep_manager() -> SleepManager:
    """构造一个不触碰真实 sleep_states.json 的 SleepManager。"""
    store = SleepStateStore(
        state_dir=Path(tempfile.gettempdir()),
        filename="verify_energy_decay_balance_absent_sleep.json",
    )
    # 该文件不存在 → load() 返回空；save 换成 no-op → 不落盘。
    store.save = lambda states: None  # type: ignore[assignment]
    manager = SleepManager(store=store)
    manager._persist = lambda: None  # type: ignore[assignment]
    return manager


def seed_state(
    manager: SleepManager, *, impact: str, nightmare: str, inertia: float
) -> SleepRuntimeState:
    """塞入一个「当天起床后」的睡眠状态。

    起点用 WAKING_UP（不是 FULLY_AWAKE）：这样 1 小时后会走真实的
    `sleep_inertia_score *= 0.5` 分支，惯性惩罚的衰减也被覆盖。
    """
    state = SleepRuntimeState(role_id=ROLE_ID, date=FIXED_DATE)
    state.phase = SleepPhase.WAKING_UP
    state.is_sleeping = False
    state.actual_wakeup_ts = wake_dt().timestamp()
    state.last_wake_ts = wake_dt().timestamp()
    state.nightmare_level = nightmare
    state.impact_level = impact
    state.impact_expires_at_ts = 0.0
    state.sleep_inertia_score = inertia
    state.sleep_debt_hours = 0.0
    manager._states[ROLE_ID] = state
    return state


def make_stats_manager() -> LifeStatsManager:
    """构造一个不读也不写真实 life_stats_state.json 的 LifeStatsManager。"""
    absent = os.path.join(
        tempfile.gettempdir(), f"verify_energy_decay_balance_absent_{os.getpid()}.json"
    )
    assert not os.path.exists(absent), f"沙箱状态文件不该存在: {absent}"
    life_stats_module._STATE_FILE = absent
    manager = LifeStatsManager(SimpleNamespace())
    manager.save_state = lambda: None  # type: ignore[assignment]
    # 饥饿/口渴跌破 10 会触发皮质醇调整，进而 import C++ 调度器扩展。
    # 该副作用与精力无关，跳过它让沙箱在无 C++ 产物的机器上也能跑。
    manager._adjust_cortisol = lambda: None  # type: ignore[assignment]
    return manager


def simulate_day(*, impact: str, nightmare: str, inertia: float):
    """按真实 tick 顺序复算整天，返回 (逐分钟 energy 序列, 逐分钟 impact_level 序列)。"""
    sleep_manager = make_sleep_manager()
    seed_state(sleep_manager, impact=impact, nightmare=nightmare, inertia=inertia)
    stats = make_stats_manager()

    energies = [float(stats.life_stats["energy"])]
    impacts = [str(stats.life_stats.get("today_sleep_impact_level") or "none")]

    cursor = wake_dt()
    for activity, minutes in DAY_SEQUENCE:
        for _ in range(minutes):
            summary = sleep_manager.get_summary(ROLE_ID, now=cursor)
            stats.decay_stats(activity, sleep_summary=summary)
            energies.append(float(stats.life_stats["energy"]))
            impacts.append(str(summary.get("impact_level") or "none"))
            cursor += timedelta(minutes=1)

    return energies, impacts


def legacy_day(impact: str) -> float:
    """旧口径复算：基速 0.1（重活动 0.2）+ 惩罚整天生效，且白天无任何恢复。"""
    energy = 100.0
    for activity, minutes in DAY_SEQUENCE:
        decay = LEGACY_HEAVY_DECAY if activity in ("working", "working_hard") else LEGACY_BASE_DECAY
        decay += LEGACY_IMPACT_EXTRA.get(impact, 0.0)
        if energy > 0:
            decay += LEGACY_INERTIA_EXTRA
        energy = max(0.0, energy - decay * minutes)
    return energy
