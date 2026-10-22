"""共用优先级词汇的守卫测试（2026-10-02 新增）。

背景：排查「角色反复催」时发现「什么该先催、多急、多久能再催一次」散落在三处
互不共享的实现里（聊天议程阶梯 / active_care 的 priority_analyzer /
daily_push_priority）。这里钉住抽出来的共用词汇：档位 + 档位到冷却时长的映射。
"""

from __future__ import annotations

from core.services.priority import (
    DEFAULT_COOLDOWN_SECONDS,
    UNLIMITED,
    PriorityLevel,
    ThrottlePolicy,
    blocked_reason,
    cooldown_seconds_for_focus,
    cooldown_seconds_for_level,
    cooldown_seconds_for_reason,
    level_of_plan_priority,
    level_of_reason,
    may_fire,
    registered_reasons,
    remaining_cooldown_seconds,
)


def test_levels_are_ordered_from_routine_to_critical():
    """档位必须可比较且顺序正确 —— 三处实现都靠「数值越大越急」。"""
    assert PriorityLevel.ROUTINE < PriorityLevel.PENDING
    assert PriorityLevel.PENDING < PriorityLevel.DUE_SOON
    assert PriorityLevel.DUE_SOON < PriorityLevel.OVERDUE
    assert PriorityLevel.OVERDUE < PriorityLevel.CRITICAL


def test_level_of_reason_known_reasons():
    assert level_of_reason("overdue") == PriorityLevel.OVERDUE
    assert level_of_reason("due_soon") == PriorityLevel.DUE_SOON
    assert level_of_reason("timed_pending") == PriorityLevel.PENDING
    assert level_of_reason("untimed_pending") == PriorityLevel.PENDING
    assert level_of_reason("meal_care") == PriorityLevel.ROUTINE
    assert level_of_reason("sleep_deprived") == PriorityLevel.CRITICAL


def test_level_of_reason_is_case_and_space_insensitive():
    assert level_of_reason("  OVERDUE ") == PriorityLevel.OVERDUE
    assert level_of_reason("Due_Soon") == PriorityLevel.DUE_SOON


def test_level_of_reason_unknown_falls_back_without_raising():
    """没登记的理由一律 ROUTINE，绝不抛 —— 这条链路上抛异常会整轮没有议程。"""
    assert level_of_reason("从没见过的理由") == PriorityLevel.ROUTINE
    assert level_of_reason("") == PriorityLevel.ROUTINE
    assert level_of_reason(None) == PriorityLevel.ROUTINE


def test_cooldown_is_shared_per_level():
    """同一档共用一个冷却值；不登记的档位落到默认值。"""
    assert cooldown_seconds_for_level(PriorityLevel.OVERDUE) == 20 * 60
    assert cooldown_seconds_for_level(PriorityLevel.DUE_SOON) == 15 * 60
    assert cooldown_seconds_for_level(PriorityLevel.PENDING) == 45 * 60
    assert cooldown_seconds_for_level(PriorityLevel.ROUTINE) == 90 * 60


def test_cooldown_for_reason_follows_level():
    assert cooldown_seconds_for_reason("overdue") == 20 * 60
    assert cooldown_seconds_for_reason("due_soon") == 15 * 60
    assert cooldown_seconds_for_reason("timed_pending") == 45 * 60
    assert cooldown_seconds_for_reason("untimed_pending") == 45 * 60


def test_cooldown_for_focus_matches_legacy_behavior():
    """逐条对齐重构前 `get_priority_probe_cooldown_seconds` 的行为。

    这条是本次抽取的核心护栏：冷却口径必须一模一样，
    否则「多久能再催一次」会在重构里被悄悄改掉。
    """
    assert cooldown_seconds_for_focus({}) == 3600
    assert cooldown_seconds_for_focus(None) == DEFAULT_COOLDOWN_SECONDS
    assert cooldown_seconds_for_focus("not-a-dict") == DEFAULT_COOLDOWN_SECONDS
    assert cooldown_seconds_for_focus({"task_probe": {}}) == 3600
    assert cooldown_seconds_for_focus({"stage": "idle"}) == 3600
    assert cooldown_seconds_for_focus({"task_probe": {"reason": "overdue"}}) == 20 * 60
    assert cooldown_seconds_for_focus({"task_probe": {"reason": "due_soon"}}) == 15 * 60
    assert cooldown_seconds_for_focus({"task_probe": {"reason": "timed_pending"}}) == 45 * 60
    assert cooldown_seconds_for_focus({"task_probe": {"reason": "untimed_pending"}}) == 45 * 60
    assert cooldown_seconds_for_focus({"portrait_priority": ["meal"]}) == 90 * 60
    # 任务与画像同时存在时以任务为准
    assert (
        cooldown_seconds_for_focus(
            {"task_probe": {"reason": "overdue"}, "portrait_priority": ["meal"]}
        )
        == 20 * 60
    )
    # 未登记的 reason 保持原实现的「落到默认」，不按档位换算
    assert cooldown_seconds_for_focus({"task_probe": {"reason": "task_follow_up"}}) == 3600


def test_registered_reasons_is_a_copy():
    """返回只读快照：调用方改它不能污染全局词汇表。"""
    snapshot = registered_reasons()
    snapshot["overdue"] = PriorityLevel.ROUTINE
    assert level_of_reason("overdue") == PriorityLevel.OVERDUE


def test_push_candidate_reasons_are_registered():
    """daily_push_priority 用到的 reason 必须全部登记，否则档位会悄悄落到 ROUTINE。

    2026-10-02 实测漏登记过 `urgent` 与 `plan_item`：
    突发状态（tired/sick）和高优先级计划项都被标成了 ROUTINE。
    """
    registered = registered_reasons()
    for reason in (
        "overdue",
        "due_soon",
        "timed_pending",
        "untimed_pending",
        "review_due",
        "streak_at_risk",
        "plan_item",
        "portrait_missing",
        "peer_chat_share",
        "fallback",
        "urgent",
    ):
        assert reason in registered, f"{reason} 未登记"
    assert level_of_reason("urgent") == PriorityLevel.CRITICAL
    assert level_of_reason("plan_item") == PriorityLevel.PENDING
    assert level_of_reason("fallback") == PriorityLevel.ROUTINE


def test_level_of_plan_priority_maps_high_normal_low():
    """计划项自带 high/normal/low，比 reason 更能反映它多急。"""
    assert level_of_plan_priority("high") == PriorityLevel.DUE_SOON
    assert level_of_plan_priority("normal") == PriorityLevel.PENDING
    assert level_of_plan_priority("low") == PriorityLevel.ROUTINE
    # 大小写/空格容错，不认识的值按 PENDING（不抛）
    assert level_of_plan_priority("HIGH") == PriorityLevel.DUE_SOON
    assert level_of_plan_priority(" normal ") == PriorityLevel.PENDING
    assert level_of_plan_priority("从没见过") == PriorityLevel.PENDING
    assert level_of_plan_priority(None) == PriorityLevel.PENDING


# ────────────────────── 节流判定（ThrottlePolicy） ──────────────────────


def test_unlimited_policy_always_fires():
    assert UNLIMITED.is_unlimited()
    assert may_fire(UNLIMITED) is True
    assert blocked_reason(UNLIMITED) == ""


def test_once_per_day_blocks_only_after_firing_today():
    policy = ThrottlePolicy(once_per_day=True)
    assert may_fire(policy, fired_today=False) is True
    assert may_fire(policy, fired_today=True) is False
    assert blocked_reason(policy, fired_today=True) == "once_per_day"


def test_chitchat_gate_needs_enough_pure_chat_turns():
    """门控语义：攒够轮数才放行 —— 与 agenda_injections 的既有口径一致。"""
    policy = ThrottlePolicy(chitchat_turns=10)
    assert may_fire(policy, chitchat_streak=9) is False
    assert may_fire(policy, chitchat_streak=10) is True
    assert may_fire(policy, chitchat_streak=11) is True
    assert "9/10" in blocked_reason(policy, chitchat_streak=9)


def test_cooldown_blocks_within_window_and_reports_remaining():
    policy = ThrottlePolicy(cooldown_seconds=1200)
    assert may_fire(policy, last_fired_ts=1000.0, now=1000.0) is False
    assert may_fire(policy, last_fired_ts=1000.0, now=2199.0) is False
    assert may_fire(policy, last_fired_ts=1000.0, now=2200.0) is True
    assert remaining_cooldown_seconds(policy, last_fired_ts=1000.0, now=1600.0) == 600
    assert remaining_cooldown_seconds(policy, last_fired_ts=1000.0, now=2200.0) == 0
    assert "600s left" in blocked_reason(policy, last_fired_ts=1000.0, now=1600.0)


def test_cooldown_zero_never_blocks():
    """cooldown_seconds=0 表示不限 —— 别把「没设冷却」当成「永久冷却」。"""
    policy = ThrottlePolicy(cooldown_seconds=0)
    assert policy.is_unlimited() is True
    assert may_fire(policy, last_fired_ts=1000.0, now=1000.0) is True
    assert remaining_cooldown_seconds(policy, last_fired_ts=1000.0, now=1000.0) == 0


def test_missing_arguments_do_not_lock_forever():
    """缺参数按「不拦」处理 —— 少传一个字段不该把议程永久锁死。"""
    assert may_fire(ThrottlePolicy(cooldown_seconds=1200)) is True
    assert may_fire(ThrottlePolicy(cooldown_seconds=1200), last_fired_ts=1000.0) is True
    assert may_fire(ThrottlePolicy(cooldown_seconds=1200), now=1000.0) is True


def test_three_dimensions_combine():
    """三个维度是「与」关系，任一拦住就不放行。"""
    policy = ThrottlePolicy(cooldown_seconds=1200, once_per_day=True, chitchat_turns=10)
    ok = dict(fired_today=False, last_fired_ts=1000.0, now=9999.0, chitchat_streak=10)
    assert may_fire(policy, **ok) is True
    assert may_fire(policy, **{**ok, "fired_today": True}) is False
    assert may_fire(policy, **{**ok, "chitchat_streak": 0}) is False
    assert may_fire(policy, **{**ok, "now": 1500.0}) is False
