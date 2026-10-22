from unittest.mock import MagicMock, patch

import pytest

from core.agents.chat_agent_components.persona_system.prompt.components.user_bio import (
    _build_health_alert_lines,
    _extract_known_sleep_time_fact,
    _render_health_alerts,
    build_bio_context_for_active_care,
    build_user_bio_context_for_chat,
)
from core.services.user_physiology.service import UserPhysiologyService


def test_chat_sleep_anchor_is_fact_only():
    status_manager = MagicMock()
    status_manager.get_status_summary.return_value = "当前无特殊状态"

    daily_manager = MagicMock()
    daily_manager.get_today_summary.return_value = (
        "昨晚睡觉：01:23\n"
        "今天起床：08:10"
    )

    with patch(
        "core.services.workspace.status_manager.get_user_status_manager",
        return_value=status_manager,
    ), patch(
        "core.services.daily.manager.get_daily_manager",
        return_value=daily_manager,
    ):
        text = build_user_bio_context_for_chat("test-user")

    assert "【用户睡眠事实锚点】" in text
    assert "last_night_bedtime=01:23" in text
    for coaching in ("禁止追问", "禁止问", "现在困吗", "必须"):
        assert coaching not in text


def test_sleep_anchor_supports_current_portrait_wording():
    """锚点正则必须认当前文案，且不被规律值/设备实测行冒充。

    2026-09-18：日记录 sleep+wakeup 齐全时渲染成「用户睡眠: HH:MM → HH:MM」，
    旧正则只认「睡觉」，锚点长期抽不出来（等于这条护栏从不生效）。
    """
    assert _extract_known_sleep_time_fact("- 用户睡眠: 13:10 → 01:19 (12h9m)") == "13:10"
    assert _extract_known_sleep_time_fact("- 用户睡眠: 13:10") == "13:10"
    assert _extract_known_sleep_time_fact("- 用户昨晚睡觉: 23:30") == "23:30"
    # 作息中位数不能冒充当天就寝事实
    assert _extract_known_sleep_time_fact("用户通常入睡: 23:30（23:00~00:30）") == ""
    # 设备实测行可能带往期日期，也不能当「昨晚」锚点
    assert (
        _extract_known_sleep_time_fact(
            "- 用户睡眠（三星健康实测，可能因摘表/未同步而不完整）: 09-17 13:11 → 19:10（5h59m）"
        )
        == ""
    )


# ─────────────────────────────────────────────────────────────
# 健康预警改成「代码判定」（2026-10-02）
#
# 改前是「★若心率过高/睡眠不足/压力大，必须立刻提醒休息」——每轮都在暗示模型
# 去提健康，实测用户睡眠 3h57m 时角色从 07:27 追问到 13:37。改后只有真的越界
# 才注入一条指名道姓的指令；没越界时连「提醒休息」四个字都不出现。
# ─────────────────────────────────────────────────────────────

_FLAG_TO_ALERT = {
    "high_heart_rate": "心率偏高",
    "low_spo2": "血氧偏低",
    "sleep_deprived": "睡眠不足",
    "high_stress": "压力偏高",
}


def test_no_health_alert_when_metrics_are_normal():
    """指标正常时必须完全不提健康——这是本次修复的核心诉求。"""
    alerts = _build_health_alert_lines(
        heart_rate=72, spo2=98, sleep_hours=7.5, stress=0.2
    )
    assert alerts == []
    assert _render_health_alerts(alerts) == ""


def test_health_alert_names_the_metric_that_crossed():
    alerts = _build_health_alert_lines(
        heart_rate=72, spo2=98, sleep_hours=3.6, stress=0.2
    )
    assert alerts == ["睡眠不足（3.6h≤5h）"]
    rendered = _render_health_alerts(alerts)
    assert "3.6h" in rendered
    assert "提醒他休息" in rendered


def test_health_alert_ignores_dirty_and_bool_values():
    """脏值和 bool 都不能被当成越界——True >= 110 会误报。"""
    assert _build_health_alert_lines(
        heart_rate=True, spo2=False, sleep_hours=None, stress=True
    ) == []
    assert _build_health_alert_lines(
        heart_rate="abc", spo2="", sleep_hours=None, stress=None
    ) == []


@pytest.mark.parametrize(
    "metrics",
    [
        {"heart_rate_bpm": 130, "spo2_percent": 90, "sleep_hours_last_night": 4.0, "stress_level": 0.9},
        {"heart_rate_bpm": 72, "spo2_percent": 98, "sleep_hours_last_night": 7.5, "stress_level": 0.2},
        {"heart_rate_bpm": 110, "spo2_percent": 92, "sleep_hours_last_night": 5.0, "stress_level": 0.85},
        {"heart_rate_bpm": 109.9, "spo2_percent": 92.1, "sleep_hours_last_night": 5.01, "stress_level": 0.849},
    ],
)
def test_prompt_alert_parity_with_service_flags(metrics):
    """prompt 侧预警必须和设备侧 _derive_flags 完全一致。

    两边各写一套阈值就会漂移：改了设备侧、prompt 侧还在按旧标准催人。
    现在共用同一份常量，这条断言把「共用」钉住。
    """
    urgent = (UserPhysiologyService()._derive_flags(metrics) or {}).get("urgent_needs") or []
    expected = {_FLAG_TO_ALERT[name] for name in urgent}
    alerts = _build_health_alert_lines(
        heart_rate=metrics.get("heart_rate_bpm"),
        spo2=metrics.get("spo2_percent"),
        sleep_hours=metrics.get("sleep_hours_last_night"),
        stress=metrics.get("stress_level"),
    )
    assert {alert.split("（")[0] for alert in alerts} == expected


def _active_care_with(sleep_hours, physio_metrics=None):
    """跑一遍 ActiveCare 注入，physio 用假服务，睡眠用指定值。"""
    status_manager = MagicMock()
    status_manager.get_status_summary.return_value = "当前无特殊状态"
    daily_manager = MagicMock()
    daily_manager.get_today_summary.return_value = "- 用户三餐: 无记录"

    physio = MagicMock()
    if physio_metrics is None:
        physio.get_latest.return_value = None
    else:
        physio.get_latest.return_value = {
            "source": "samsung_health",
            "is_stale": False,
            "metrics": physio_metrics,
        }

    with patch(
        "core.services.workspace.status_manager.get_user_status_manager",
        return_value=status_manager,
    ), patch(
        "core.services.daily.manager.get_daily_manager",
        return_value=daily_manager,
    ), patch(
        "core.services.active_care.decision.context_gatherer._parse_sleep_duration_from_daily_record",
        return_value=sleep_hours,
    ), patch(
        "core.services.user_physiology.service.get_user_physiology_service",
        return_value=physio,
    ):
        return build_bio_context_for_active_care("test-user")


def test_active_care_sleep_deprived_injects_alert():
    text = _active_care_with(3.6)
    assert "睡眠=3.6h" in text
    assert "睡眠不足" in text
    assert "提醒他休息" in text


def test_active_care_enough_sleep_has_no_coaching():
    """睡够了就只给事实——不许出现任何「提醒休息」类指令。"""
    text = _active_care_with(7.5)
    assert "睡眠=7.5h" in text
    for coaching in ("提醒休息", "必须", "预警", "若睡眠不足"):
        assert coaching not in text


def test_active_care_normal_physio_has_no_coaching():
    """设备指标全正常时也不提健康，且睡眠事实仍然照给。"""
    text = _active_care_with(
        7.5,
        physio_metrics={
            "heart_rate_bpm": 72,
            "spo2_percent": 98,
            "stress_level": 0.2,
        },
    )
    assert "心率=72" in text
    assert "睡眠=7.5h" in text
    for coaching in ("提醒休息", "必须", "预警"):
        assert coaching not in text
