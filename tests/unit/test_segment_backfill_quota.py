"""回填调度器：MiniMax Token Plan 用量上限（429 + 2056）要切到 DeepSeek，纯限流不切。"""

from __future__ import annotations

from scripts.maintenance.segment_backfill.scheduler import DirectScheduler

PLAN_LIMIT = (
    '{"type":"error","error":{"type":"rate_limit_error","message":"已达到 Token Plan 用量上限：'
    '请升级 Token Plan 套餐或购买积分补充用量。 (2056)","http_code":"429"}}'
)
RATE_LIMIT = '{"type":"error","error":{"type":"rate_limit_error","message":"请求过于频繁"}}'


def test_token_plan_usage_cap_switches_to_fallback():
    scheduler = DirectScheduler("minimax", quota_fallback="cloud:deepseek:aveline:deepseek-v4-flash")
    assert scheduler._switch_quota_fallback("minimax", PLAN_LIMIT) is True
    assert scheduler.quota_exhausted and scheduler.usage["quota_switch"] == 1
    assert scheduler._route("cloud:minimax:plan:MiniMax-M3")[0] == "deepseek"


def test_plain_rate_limit_does_not_switch():
    scheduler = DirectScheduler("minimax", quota_fallback="cloud:deepseek:aveline:deepseek-v4-flash")
    assert scheduler._switch_quota_fallback("minimax", RATE_LIMIT) is False
    assert not scheduler.quota_exhausted
