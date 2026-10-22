"""翻旧日记策略层（policy）单测。

只测纯函数：时段分桶 / 概率加深 / 深度抽样 / 文案模板。
随机性一律用固定 seed 的 random.Random，时钟直接传 datetime，不碰真实时间。
"""
from __future__ import annotations

import random
from datetime import datetime

from core.services.journal.diary_reread.policy import (
    MAX_STREAK,
    RECENCY_BUCKETS,
    SleepSchedule,
    build_reread_content,
    build_reread_tags,
    classify_time_bucket,
    effective_probability,
    format_found_date,
    normalize_excerpt,
    resolve_sleep_schedule,
    sample_days_back,
)

# aveline：07:00 起 / 23:00 睡（工作日）
_AVELINE = SleepSchedule(wake_min=7 * 60, sleep_min=23 * 60)
# yeye：09:00 起 / 02:00 睡（熬夜冠军）
_YEYE = SleepSchedule(wake_min=9 * 60, sleep_min=2 * 60)


def _dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 12, hour, minute)


# ── 时段分桶 ───────────────────────────────────────────────


def test_bucket_late_after_bedtime_and_deep_night():
    # 就寝点之后
    assert classify_time_bucket(_dt(23, 47), _AVELINE) == "late"
    assert classify_time_bucket(_dt(23, 0), _AVELINE) == "late"
    # 跨过午夜的深夜窗口，与角色作息无关
    assert classify_time_bucket(_dt(0, 30), _AVELINE) == "late"
    assert classify_time_bucket(_dt(4, 59), _AVELINE) == "late"
    # 夜猫子角色（yeye 02:00 才睡）：跨过午夜仍在深夜窗口内
    assert classify_time_bucket(_dt(1, 0), _YEYE) == "late"
    assert classify_time_bucket(_dt(3, 0), _YEYE) == "late"


def test_bucket_early_before_wake():
    assert classify_time_bucket(_dt(6, 30), _AVELINE) == "early"
    assert classify_time_bucket(_dt(5, 0), _AVELINE) == "early"
    # 深夜窗口优先于「起床前」
    assert classify_time_bucket(_dt(4, 59), _AVELINE) == "late"


def test_bucket_stumble_daytime():
    assert classify_time_bucket(_dt(9, 0), _AVELINE) == "stumble"
    assert classify_time_bucket(_dt(14, 0), _AVELINE) == "stumble"
    assert classify_time_bucket(_dt(22, 0), _AVELINE) == "stumble"
    # 夜猫子的 23:00 还没到她就寝点（02:00），不算深夜
    assert classify_time_bucket(_dt(23, 0), _YEYE) == "stumble"


def test_bucket_night_owl_before_bedtime_is_not_late():
    # ling 02:00 才睡：00:30 属于深夜窗口（past midnight），
    # 但 23:00 这种「还没睡但也没过就寝点」的不能误判成深夜
    assert classify_time_bucket(_dt(23, 30), _YEYE) == "stumble"
    assert classify_time_bucket(_dt(7, 0), _YEYE) == "early"


# ── 触发概率 ───────────────────────────────────────────────


def test_base_probabilities_match_agreed_values():
    assert effective_probability("late", 0) == 0.45
    assert effective_probability("early", 0) == 0.20
    assert effective_probability("stumble", 0) == 0.12


def test_late_streak_bonus_caps_at_second_night():
    assert effective_probability("late", 1) == 0.55  # 第 2 晚 +0.10
    assert effective_probability("late", 2) == 0.65  # 第 3 晚起 +0.20
    assert effective_probability("late", 5) == 0.65  # 封顶
    assert effective_probability("late", 99) == 0.65


def test_non_late_buckets_have_no_streak_bonus():
    assert effective_probability("early", 3) == 0.20
    assert effective_probability("stumble", 3) == 0.12


# ── 深度抽样 ───────────────────────────────────────────────


def test_sample_days_back_within_table_ranges():
    rng = random.Random(20261012)
    lows = [low for low, _, _ in RECENCY_BUCKETS]
    for _ in range(500):
        days = sample_days_back(rng, 1)
        assert any(low <= days <= (high if high is not None else 10**9)
                   for low, high, _ in RECENCY_BUCKETS)
        assert days >= lows[0]


def test_deep_bias_shifts_distribution_later():
    """streak>=3 时远档权重 ×2：大样本下均值应明显后移（固定 seed 保证稳定）。"""
    plain_rng = random.Random(7)
    plain = [sample_days_back(plain_rng, 1) for _ in range(2000)]
    biased_rng = random.Random(7)
    biased = [sample_days_back(biased_rng, MAX_STREAK) for _ in range(2000)]
    assert sum(biased) / len(biased) > sum(plain) / len(plain) + 5


def test_sample_days_back_deterministic_with_fixed_seed():
    rng = random.Random(42)
    first = [sample_days_back(rng, 2) for _ in range(10)]
    rng2 = random.Random(42)
    second = [sample_days_back(rng2, 2) for _ in range(10)]
    assert first == second


# ── 文案模板 ───────────────────────────────────────────────


def test_normalize_excerpt_collapses_and_truncates():
    assert normalize_excerpt("  多行\n内容\t保留  ") == "多行 内容 保留"
    long_text = "长" * 100
    trimmed = normalize_excerpt(long_text)
    assert trimmed.endswith("…")
    assert len(trimmed) <= 41


def test_format_found_date_same_year_short_cross_year_full():
    anchor = datetime(2026, 10, 12)
    assert format_found_date(datetime(2026, 10, 1), anchor) == "10-01"
    assert format_found_date(datetime(2025, 12, 31), anchor) == "2025-12-31"


def test_build_reread_content_flavors():
    anchor = datetime(2026, 10, 12)
    found = datetime(2026, 10, 5)
    late = build_reread_content("late", 7, found, anchor, "测试摘录")
    early = build_reread_content("early", 7, found, anchor, "测试摘录")
    stumble = build_reread_content("stumble", 7, found, anchor, "测试摘录")
    assert late.startswith("睡不着") and "7天前（10-05）" in late and "测试摘录" in late
    assert early.startswith("醒得早") and "7天前（10-05）" in early
    assert stumble.startswith("偶然翻到") and "7天前（10-05）" in stumble


def test_build_reread_tags_carry_bucket_and_depth():
    assert build_reread_tags("late", 12) == ["翻旧日记", "深夜失眠", "12天前"]
    assert build_reread_tags("early", 2) == ["翻旧日记", "清早闲翻", "2天前"]
    assert build_reread_tags("stumble", 30) == ["翻旧日记", "偶然翻到", "30天前"]


# ── 作息解析（读真实配置） ────────────────────────────────


def test_resolve_schedule_aveline_weekday():
    schedule = resolve_sleep_schedule("aveline", datetime(2026, 10, 12))  # 周一
    assert schedule.wake_min == 7 * 60
    assert schedule.sleep_min == 23 * 60


def test_resolve_schedule_ling_weekend_differs():
    # ling 工作日 07:00/23:30，休息日 09:00/00:30
    weekday = resolve_sleep_schedule("ling", datetime(2026, 10, 12))  # 周一
    weekend = resolve_sleep_schedule("ling", datetime(2026, 10, 17))  # 周六
    assert weekday.wake_min == 7 * 60 and weekday.sleep_min == 23 * 60 + 30
    assert weekend.wake_min == 9 * 60 and weekend.sleep_min == 30


def test_resolve_schedule_yeye_is_night_owl():
    weekday = resolve_sleep_schedule("yeye", datetime(2026, 10, 12))
    assert weekday.wake_min == 9 * 60 and weekday.sleep_min == 2 * 60


def test_resolve_schedule_unknown_role_falls_back():
    schedule = resolve_sleep_schedule("no_such_role", datetime(2026, 10, 12))
    assert schedule.wake_min == 7 * 60
    assert schedule.sleep_min == 23 * 60
