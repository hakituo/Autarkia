"""验证精力（energy）平衡修复：睡眠影响按时长过期 + 白天不再只降不升

背景（2026-10-03）：
    角色持续对用户说"没力气、精力是 0"，`cache/life_stats_state.json` 里 energy 确实是 0。
    两个叠在一起的缺陷：

    A. 睡眠影响永不失效
       `sleep_manager._maybe_roll_nightmare` 把 `quality_impact.duration_hours`
       写成 2/4/10 小时，但**全仓没有任何地方读它**；`impact_level` 只在跨天
       `_reset_daily_fields` 清零。于是一次 severe 噩梦会惩罚一整天，
       起床后每分钟多扣 0.1 energy。

    B. 精力白天没有任何恢复路径
       `LifeStatsManager.decay_stats` 里基速 0.1/min（`working` 才 0.2），
       A/B 叠加后 0.22/min；而恢复只有 `activity == "sleeping"` 一条。
       100 ÷ 0.22 = 454 分钟 ≈ 7.6 小时 —— 08:33 起床约 16:07 归零，
       之后整晚钉在 0（食物只给 nutrition.energy，5~15 点且立即只结算 40%）。
       即使没有任何惩罚，0.1/min × 16 小时也要掉 96 点，晚上照样见底。

本轮修复：
- `SleepRuntimeState` 新增 `impact_expires_at_ts`，`SleepManager._apply_impact_expiry`
  在「起床锚点 + `_IMPACT_DURATION_HOURS[level]`」之后自动清零 `impact_level`
  （旧状态文件无锚点时按 `last_wake_ts` 补锚，不会把已惩罚半天的角色再续一整个时长）；
- 精力口径收敛到 `life_stats.resolve_energy_delta` 一处：按活动强度分档
  （休息类 0.03 / 日常 0.07 / 重活动 0.12），睡眠影响惩罚减半
  （0.01 / 0.02 / 0.04），惯性惩罚 0.01；`ActorManager` 也改走同一函数，
  不再各写一套 0.1/min；
- 睡眠恢复口径不变（基础 0.5，按 sleep_debt / 噩梦下调，下限 0.12）。

断言：
    1. 分档单调性：睡眠恢复 > 休息类 > 日常 > 重活动，且惩罚正确叠加；
    2. 普通一天结束仍剩合理精力，且全天不归零；
    3. severe 日明显更低但依然 > 0（不再被钉在 0），惩罚只持续 10 小时；
    4. 同一序列按旧口径复算必然归零（证明修复确实改变了结果）；
    5. `impact_level` 按时长自动清零；未到期时保持不变；旧状态文件补锚不续期；
    6. `ActorManager` 与全局共用同一精力口径。

沙箱（固定日程、假状态、不落盘）见同目录 `energy_decay_sandbox.py`；
本脚本只做断言与编排，运行：`venv_cpu\\Scripts\\python.exe tests\\scripts\\role_sleep\\verify_energy_decay_balance.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_DIR = Path(__file__).resolve().parent
for _p in (str(PROJECT_ROOT), str(_SCRIPT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from energy_decay_sandbox import (  # noqa: E402
    legacy_day,
    make_sleep_manager,
    seed_state,
    simulate_day,
    wake_dt,
)
from core.services.life_simulation.actor_manager import ActorManager  # noqa: E402
from core.services.life_simulation.life_stats import resolve_energy_delta  # noqa: E402
from core.services.life_simulation.sleep_manager import (  # noqa: E402
    _IMPACT_DURATION_HOURS,
)

_PASSED = 0
_FAILED = 0


def _ok(msg: str) -> None:
    global _PASSED
    _PASSED += 1
    print(f"  [PASS] {msg}")


def _fail(msg: str, detail: str = "") -> None:
    global _FAILED
    _FAILED += 1
    print(f"  [FAIL] {msg}")
    if detail:
        print(f"         {detail}")


def _section(title: str) -> None:
    print(f"\n[{title}]")


def test_delta_ordering() -> None:
    """断言 1：分档单调性 + 惩罚叠加。"""
    _section("1. resolve_energy_delta 分档单调性")
    sleeping = resolve_energy_delta("sleeping", sleep_phase="sleeping")
    light = resolve_energy_delta("phone_scrolling")
    normal = resolve_energy_delta("walking")
    heavy = resolve_energy_delta("exercising")

    if sleeping > 0 > light:
        _ok(f"睡眠恢复 {sleeping:+.3f} > 0 > 休息类消耗 {light:+.3f}")
    else:
        _fail("睡眠/休息类方向不对", f"sleeping={sleeping} light={light}")
    if light > normal > heavy:
        _ok(f"分档递减：休息 {light:+.3f} > 日常 {normal:+.3f} > 重活动 {heavy:+.3f}")
    else:
        _fail("分档不是单调递减", f"light={light} normal={normal} heavy={heavy}")

    plain = resolve_energy_delta("walking")
    impacted = resolve_energy_delta("walking", impact_level="severe")
    inertia = resolve_energy_delta("walking", impact_level="severe", inertia_score=30.25)
    if plain > impacted > inertia:
        _ok(f"惩罚叠加：无惩罚 {plain:+.3f} > severe {impacted:+.3f} > severe+惯性 {inertia:+.3f}")
    else:
        _fail("睡眠影响/惯性惩罚没有叠加到消耗上", f"{plain} {impacted} {inertia}")

    phase_only = resolve_energy_delta("idle", sleep_phase="sleeping")
    if phase_only > 0:
        _ok("phase=sleeping 时即使 activity 不是 sleeping 也走恢复（不再误扣）")
    else:
        _fail("phase=sleeping 未被识别为睡眠恢复", f"delta={phase_only:+.3f}")


def test_plain_day_never_zeroes() -> None:
    """断言 2：普通一天不归零且收尾合理。"""
    _section("2. 普通一天（无睡眠影响）")
    energies, _ = simulate_day(impact="none", nightmare="none", inertia=0.0)
    final, lowest = energies[-1], min(energies)
    if lowest > 0:
        _ok(f"全天最低 {lowest:.1f} > 0（不会归零）")
    else:
        _fail("普通一天仍然归零", f"最低={lowest:.1f}")
    if 30.0 <= final <= 75.0:
        _ok(f"收尾 {final:.1f} 落在 [30, 75]（醒 100 → 睡前还有余量）")
    else:
        _fail("收尾值不合理", f"final={final:.1f}，期望 [30, 75]")


def test_severe_day_stays_positive() -> None:
    """断言 3：severe 日不再被钉在 0，且惩罚只持续 10 小时。"""
    _section("3. severe 噩梦日（惩罚 10 小时 + 惯性 30.25）")
    plain, _ = simulate_day(impact="none", nightmare="none", inertia=0.0)
    severe, impacts = simulate_day(impact="severe", nightmare="severe", inertia=30.25)
    final = severe[-1]

    if min(severe) > 0:
        _ok(f"全天最低 {min(severe):.1f} > 0（不再被钉在 0）")
    else:
        _fail("severe 日仍归零", f"最低={min(severe):.1f}")
    if final < plain[-1]:
        _ok(f"severe 收尾 {final:.1f} 低于普通日 {plain[-1]:.1f}（惩罚仍然生效）")
    else:
        _fail("severe 日没有比普通日更低", f"severe={final:.1f} plain={plain[-1]:.1f}")
    if 10.0 <= final <= 55.0:
        _ok(f"severe 收尾 {final:.1f} 落在 [10, 55]（明显疲惫但还有电）")
    else:
        _fail("severe 收尾值不合理", f"final={final:.1f}，期望 [10, 55]")

    # impacts[0] 是初始快照（none），第 i 项对应第 i 分钟。
    active = [i for i, level in enumerate(impacts) if level != "none"]
    if not active:
        _fail("severe 日 impact_level 从未生效")
        return
    last_active = active[-1]
    if 595 <= last_active <= 605:
        _ok(
            f"impact_level 持续到第 {last_active} 分钟（约 {last_active / 60:.1f}h）"
            f"后失效，不再持续整天"
        )
    else:
        _fail("惩罚时长不是 severe 的 10 小时", f"last_active={last_active}")
    if all(level == "none" for level in impacts[last_active + 1 :]):
        _ok("失效后不再回弹")
    else:
        _fail("失效后 impact_level 又变回非 none")


def test_legacy_baseline_zeroes() -> None:
    """断言 4：旧口径在同一序列上确实归零（对照臂）。"""
    _section("4. 对照臂：旧口径复算")
    legacy = legacy_day("severe")
    if legacy <= 0.0:
        _ok(f"旧口径同一序列收尾 {legacy:.1f}（确实归零，说明修复改变了结果）")
    else:
        _fail("旧口径没有归零，说明活动序列取样不足以体现问题", f"legacy={legacy:.1f}")


def test_impact_expiry_semantics() -> None:
    """断言 5：impact_level 过期语义与锚点规则。"""
    _section("5. SleepManager impact_level 过期语义")
    manager = make_sleep_manager()
    seed_state(manager, impact="severe", nightmare="severe", inertia=30.25)

    within = manager.get_summary("aveline", now=wake_dt().replace(hour=17, minute=30))
    if within["impact_level"] == "severe":
        _ok("起床 9 小时后 severe 仍在（10 小时窗口内不清）")
    else:
        _fail("惩罚提前失效", f"impact_level={within['impact_level']}")

    expired_at = wake_dt().replace(hour=18, minute=31)
    summary = manager.get_summary("aveline", now=expired_at)
    state = manager.get_state("aveline", now=expired_at)
    if summary["impact_level"] == "none" and state.impact_expires_at_ts == 0.0:
        _ok("起床 10h01m 后 severe 已清零，锚点同时复位")
    else:
        _fail(
            "惩罚没有按时失效",
            f"impact_level={summary['impact_level']} expires={state.impact_expires_at_ts}",
        )

    # 旧状态文件（无锚点）按 last_wake_ts 补锚，而不是从"现在"起算续期。
    manager2 = make_sleep_manager()
    stale = seed_state(manager2, impact="severe", nightmare="severe", inertia=0.0)
    stale.impact_expires_at_ts = 0.0
    later = manager2.get_summary("aveline", now=wake_dt().replace(hour=19, minute=30))
    if later["impact_level"] == "none":
        _ok("无锚点的旧状态按 last_wake_ts 补锚后立即判为过期（不续一整个时长）")
    else:
        _fail("旧状态被按『现在』起算而续期", f"impact_level={later['impact_level']}")

    durations = dict(_IMPACT_DURATION_HOURS)
    if durations["mild"] < durations["medium"] < durations["severe"]:
        _ok(f"时长分档单调：{durations}")
    else:
        _fail("时长分档不单调", str(durations))

    manager3 = make_sleep_manager()
    seed_state(manager3, impact="mild", nightmare="mild", inertia=0.0)
    manager3.get_summary("aveline", now=wake_dt().replace(hour=8, minute=35))
    state3 = manager3.get_state("aveline", now=wake_dt().replace(hour=8, minute=36))
    expected = wake_dt().timestamp() + 2 * 3600
    if abs(state3.impact_expires_at_ts - expected) < 1.0:
        _ok("mild 锚点 = last_wake_ts + 2h")
    else:
        _fail("锚点不是 last_wake_ts", f"expires={state3.impact_expires_at_ts} 期望={expected}")


def test_actor_path_shares_policy() -> None:
    """断言 6：ActorManager 按角色分别结算，且与全局共用同一口径。"""
    _section("6. ActorManager 复用同一精力口径")
    manager = ActorManager()
    manager._actor_life_states = {
        "aveline": {"energy": 100.0, "hunger": 100.0, "thirst": 100.0, "mood_score": 80.0},
        "ling": {"energy": 90.0, "hunger": 100.0, "thirst": 100.0, "mood_score": 80.0},
    }
    manager._maybe_save_actor_states = lambda: None  # type: ignore[assignment]
    manager.tick_actor_life_states(
        "walking", activity_by_role={"aveline": "walking", "ling": "sleeping"}
    )
    awake = manager.get_actor_life_state("aveline")["energy"]
    asleep = manager.get_actor_life_state("ling")["energy"]
    expect_awake = 100.0 + resolve_energy_delta("walking")
    expect_asleep = 90.0 + resolve_energy_delta("sleeping", sleep_phase="sleeping")
    if abs(awake - expect_awake) < 1e-6 and abs(asleep - expect_asleep) < 1e-6:
        _ok(f"按角色分别结算且与全局口径一致（走路 {awake:.3f} / 睡觉 {asleep:.3f}）")
    else:
        _fail(
            "ActorManager 与 resolve_energy_delta 结果不一致",
            f"awake={awake} 期望={expect_awake} asleep={asleep} 期望={expect_asleep}",
        )


def main() -> int:
    print("=" * 64)
    print("精力（energy）平衡修复 验证")
    print("=" * 64)

    test_delta_ordering()
    test_plain_day_never_zeroes()
    test_severe_day_stays_positive()
    test_legacy_baseline_zeroes()
    test_impact_expiry_semantics()
    test_actor_path_shares_policy()

    print("\n" + "=" * 64)
    print(f"结果: {_PASSED} 通过 / {_FAILED} 失败")
    print("=" * 64)
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
