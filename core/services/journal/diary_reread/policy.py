"""日记翻旧（diary reread）策略层。

纯函数与常量，不依赖 service / storage 实例，方便单测：
- 时段分桶：深夜 / 清早 / 偶然（按角色自身作息判定）
- 触发概率：基础概率 + streak 连翻加深
- 回看深度：days_back 加权抽样表
- 文案模板：命中后写入日记条目的风味短句

所有概率与权重集中在本模块，调口味只改这里。
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from core.utils.logger import get_logger
from core.utils.time_utils import parse_hhmm

logger = get_logger("DiaryRereadPolicy")

# ── 常量 ───────────────────────────────────────────────────

#: 深夜窗口结束时刻（分钟）。00:00–04:59 对任何角色都算「深夜」，
#: 与她自己的作息无关——凌晨还在写日记就是睡不着。
DEEP_NIGHT_END_MIN = 5 * 60

#: 各时段基础触发概率（用户 2026-10-12 拍板）
BASE_PROBABILITY = {"late": 0.45, "early": 0.20, "stumble": 0.12}

#: 连续翻旧的最大晚数（streak 上限，用户 2026-10-12 拍板）
MAX_STREAK = 5

#: 深夜档连翻加深：key 为「此前已连续翻旧的晚数」
#: 第 2 晚 +0.10，第 3 晚起 +0.20 封顶。
LATE_STREAK_BONUS = ((2, 0.20), (1, 0.10))

#: days_back 加权抽样表：(最小天数, 最大天数(含), None 表示开区间, 权重)
#: 权重集中在前一周——刚过去的事最常被翻到；越久远越难翻到。
RECENCY_BUCKETS: Tuple[Tuple[int, Optional[int], float], ...] = (
    (1, 3, 0.45),
    (4, 7, 0.25),
    (8, 30, 0.20),
    (31, 180, 0.07),
    (181, 365, 0.025),
    (366, None, 0.005),
)

#: streak 达到该值后，>= DEEP_BUCKET_MIN_DAYS 的远档权重 ×2（连着翻会越翻越久远）
DEEP_BUCKET_MIN_DAYS = 31
DEEP_BIAS_STREAK = 3

#: 开区间桶（>365 天）的抽样上限，日记数据通常远小于此
OPEN_BUCKET_MAX_DAYS = 730

#: 作息解析失败时的兜底值（07:00 起 / 23:00 睡）
DEFAULT_WAKE_HHMM = "07:00"
DEFAULT_SLEEP_HHMM = "23:00"

#: 分桶中文标签（写入日记条目的 tags）
BUCKET_LABELS = {"late": "深夜失眠", "early": "清早闲翻", "stumble": "偶然翻到"}

#: 分桶 → mood（free-form，仅作展示）
BUCKET_MOODS = {"late": "restless", "early": "neutral", "stumble": "neutral"}

#: 风味文案 excerpt 最大长度
EXCERPT_MAX_LEN = 40


# ── 时段分桶 ───────────────────────────────────────────────


@dataclass(frozen=True)
class SleepSchedule:
    """角色某天的起床 / 就寝时刻（分钟，0–1439）。"""

    wake_min: int
    sleep_min: int


def resolve_sleep_schedule(role_id: str, dt: datetime) -> SleepSchedule:
    """按角色当天作息解析起床/就寝分钟数。

    取 `config/yaml/character_day_types.yaml` 同步后的 weekday/weekend 作息
    （经 `character_daily.config.load_schedule_templates()`），
    角色缺失或解析失败时兜底 07:00 / 23:00。
    """
    wake = parse_hhmm(DEFAULT_WAKE_HHMM)
    sleep = parse_hhmm(DEFAULT_SLEEP_HHMM)
    wake = wake if wake is not None else 7 * 60
    sleep = sleep if sleep is not None else 23 * 60
    try:
        from core.services.character_daily.config import load_schedule_templates

        template = load_schedule_templates().get(str(role_id or "").strip())
        if template is None:
            return SleepSchedule(wake_min=wake, sleep_min=sleep)
        profile = template.sleep_profile
        is_weekend = dt.weekday() >= 5
        wake_src = ""
        sleep_src = ""
        if profile is not None:
            if is_weekend:
                wake_src = profile.weekend_wake_time or profile.weekday_wake_time
                sleep_src = profile.weekend_sleep_time or profile.weekday_sleep_time
            else:
                wake_src = profile.weekday_wake_time
                sleep_src = profile.weekday_sleep_time
        parsed_wake = parse_hhmm(wake_src) if wake_src else None
        parsed_sleep = parse_hhmm(sleep_src) if sleep_src else None
        if parsed_wake is None:
            parsed_wake = parse_hhmm(template.wake_time)
        if parsed_sleep is None:
            parsed_sleep = parse_hhmm(template.sleep_time)
        if parsed_wake is not None:
            wake = parsed_wake
        if parsed_sleep is not None:
            sleep = parsed_sleep
    except Exception as exc:  # noqa: BLE001 - 日程缺失不能阻断翻旧判定
        logger.warning("解析角色作息失败 role=%s: %s", role_id, exc)
    return SleepSchedule(wake_min=wake, sleep_min=sleep)


def classify_time_bucket(dt: datetime, schedule: SleepSchedule) -> str:
    """把写日记的时刻分入 late / early / stumble 三桶。

    - late：深夜窗口内（00:00–04:59），或就寝点之后（仅作息不跨零点时）
    - early：起床时刻之前（且不在深夜窗口）
    - stumble：其余时段（白天/傍晚正常时间）
    """
    minute = dt.hour * 60 + dt.minute
    if minute < DEEP_NIGHT_END_MIN:
        return "late"
    if schedule.sleep_min > schedule.wake_min and minute >= schedule.sleep_min:
        return "late"
    if minute < schedule.wake_min:
        return "early"
    return "stumble"


# ── 触发概率 ───────────────────────────────────────────────


def effective_probability(bucket: str, prior_streak: int) -> float:
    """该时段的最终触发概率（含深夜档连翻加深，封顶 1.0）。"""
    probability = BASE_PROBABILITY.get(bucket, 0.0)
    if bucket == "late":
        prior = max(0, int(prior_streak))
        for threshold, bonus in LATE_STREAK_BONUS:
            if prior >= threshold:
                probability += bonus
                break
    return min(1.0, max(0.0, probability))


# ── 回看深度抽样 ───────────────────────────────────────────


def sample_days_back(rng: random.Random, effective_streak: int) -> int:
    """按加权表抽样「翻到多久之前」的天数。

    effective_streak >= DEEP_BIAS_STREAK 时，远档（>=31 天）权重 ×2 后归一化。
    """
    weights: List[float] = [weight for _, _, weight in RECENCY_BUCKETS]
    if effective_streak >= DEEP_BIAS_STREAK:
        weights = [
            weight * 2 if low >= DEEP_BUCKET_MIN_DAYS else weight
            for (low, _, weight) in RECENCY_BUCKETS
        ]
    total = sum(weights)
    if total <= 0:
        return RECENCY_BUCKETS[0][0]
    roll = rng.random() * total
    accumulated = 0.0
    for (low, high, _), weight in zip(RECENCY_BUCKETS, weights):
        accumulated += weight
        if roll <= accumulated:
            upper = high if high is not None else OPEN_BUCKET_MAX_DAYS
            return rng.randint(low, upper)
    return RECENCY_BUCKETS[0][0]


# ── 文案模板 ───────────────────────────────────────────────


def normalize_excerpt(content: Optional[str]) -> str:
    """把旧日记正文压成单行短摘录。"""
    text = " ".join(str(content or "").split())
    if len(text) > EXCERPT_MAX_LEN:
        return text[:EXCERPT_MAX_LEN] + "…"
    return text


def format_found_date(found_date: datetime, anchor_date: datetime) -> str:
    """翻到日期展示：同年只显示 MM-DD，跨年带年份。"""
    if found_date.year != anchor_date.year:
        return found_date.strftime("%Y-%m-%d")
    return found_date.strftime("%m-%d")


def build_reread_content(
    bucket: str, days_back: int, found_date: datetime, anchor_date: datetime, excerpt: str
) -> str:
    """按时段生成翻旧日记的风味短句。"""
    date_str = format_found_date(found_date, anchor_date)
    quoted = f"「{excerpt}」" if excerpt else ""
    if bucket == "late":
        return f"睡不着，翻了翻之前的日记。看到{days_back}天前（{date_str}）那篇{quoted}"
    if bucket == "early":
        return f"醒得早，没事翻了翻以前的日记。看到{days_back}天前（{date_str}）那篇{quoted}"
    return f"偶然翻到{days_back}天前（{date_str}）的日记{quoted}"


def build_reread_tags(bucket: str, days_back: int) -> List[str]:
    """翻旧日记条目的 tags。"""
    return ["翻旧日记", BUCKET_LABELS.get(bucket, bucket), f"{days_back}天前"]


def reread_mood(bucket: str) -> str:
    return BUCKET_MOODS.get(bucket, "neutral")


def summary_read_depth_days(anchor_date, target_date) -> int:
    """读每日/月度总结时的「翻旧深度」（天）。

    读当天/当月的总结深度为 0（不算翻旧）；目标日期早于锚点时返回
    相差天数；未来日期（如读当月总结）钳到 0。
    """
    try:
        delta = (anchor_date - target_date).days
    except (TypeError, ValueError):
        return 0
    return max(0, int(delta))
