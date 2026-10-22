"""作息（sleep_cycle）的记录与修正（从 manager.py 拆出的 SleepMixin）。

职责：睡眠时长计算、起床/入睡记录、用户手动修正。
起床来源优先级 `WAKEUP_SOURCE_PRIORITIES` 定义在门面的类上，这里通过 self 读。

拆分口径见 manager.py 的模块 docstring。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time, now_str

logger = get_logger("DAILY_MANAGER")


class SleepMixin:
    """作息记录与修正。"""

    def _calc_sleep_duration(self, sleep_time: str, wakeup_time: str) -> Optional[str]:
        """计算睡眠时长，返回如 '11h23m' 格式

        合理性校验：sleep_cycle 记录的是夜间主睡眠，正常时长在 1h~16h 之间。
        超出此范围说明 sleep/wakeup 字段被误填（例如把聊天时间当成睡觉时间），
        此时返回 None 避免把错误时长（如 "31m" 或 "22h45m"）展示给 AI。
        """
        try:
            sh, sm = map(int, sleep_time.split(":"))
            wh, wm = map(int, wakeup_time.split(":"))
            sleep_min = sh * 60 + sm
            wakeup_min = wh * 60 + wm
            # 如果 wakeup < sleep，说明跨天了（凌晨睡，下午起）
            if wakeup_min < sleep_min:
                wakeup_min += 24 * 60
            diff = wakeup_min - sleep_min
            # 合理性校验：< 1h 或 > 16h 视为误填，不返回时长
            if diff <= 0 or diff < 60 or diff > 16 * 60:
                return None
            h = diff // 60
            m = diff % 60
            if h > 0 and m > 0:
                return f"{h}h{m}m"
            elif h > 0:
                return f"{h}h"
            else:
                return f"{m}m"
        except (ValueError, AttributeError):
            return None

    def _update_sleep_cycle_duration(self, data: Dict[str, Any]) -> None:
        """更新 sleep_cycle 的 duration 字段"""
        sc = data.get("sleep_cycle") or {}
        sleep_time = sc.get("sleep")
        wakeup_time = sc.get("wakeup")
        if sleep_time and wakeup_time:
            sc["duration"] = self._calc_sleep_duration(sleep_time, wakeup_time)
            data["sleep_cycle"] = sc

    def record_wakeup(
        self,
        time_str: Optional[str] = None,
        *,
        source: Optional[str] = None,
        target_date: Optional[str] = None,
        force: bool = False,
    ) -> str:
        """记录起床时间，并按来源可靠性防止错误覆盖。"""
        has_explicit_time = bool(time_str)
        if not time_str:
            time_str = now_str("%H:%M")
        record_date = self._normalize_date(target_date)
        default_source = "chat_explicit_time" if has_explicit_time else "chat_inferred"
        normalized_source = str(source or default_source).strip() or default_source
        incoming_priority = self.WAKEUP_SOURCE_PRIORITIES.get(normalized_source, 0)
        with self._with_record_lock(record_date):
            data = self._load_record(record_date)
            sc = data["sleep_cycle"]
            existing_wakeup = sc.get("wakeup")
            existing_source = str(sc.get("wakeup_source") or "legacy")
            existing_priority = self.WAKEUP_SOURCE_PRIORITIES.get(existing_source, 0)

            if existing_wakeup and not force:
                if existing_priority > incoming_priority:
                    logger.info(
                        "保留更可靠的起床时间: existing=%s(%s), ignored=%s(%s)",
                        existing_wakeup,
                        existing_source,
                        time_str,
                        normalized_source,
                    )
                    return f"Kept existing wakeup: {existing_wakeup} ({existing_source})"
                # 聊天推断不应因后续多轮对话持续向后漂移。
                if (
                    existing_priority == incoming_priority
                    and normalized_source in {"chat_inferred", "chat_explicit_time"}
                    and existing_wakeup != time_str
                ):
                    return f"Kept existing wakeup: {existing_wakeup} ({existing_source})"

            sc["wakeup"] = time_str
            sc["wakeup_source"] = normalized_source
            sc["wakeup_recorded_at"] = now_str("%Y-%m-%dT%H:%M:%S%z")
            data["sleep_cycle"] = sc
            self._update_sleep_cycle_duration(data)
            self._save_record(data, record_date)
        return f"Recorded wakeup: {time_str} ({normalized_source}, {record_date})"

    def _resolve_sleep_record_date(
        self, time_str: Optional[str] = None, now_dt: Optional[datetime] = None
    ) -> str:
        current_dt = now_dt or get_current_time()
        target = current_dt.strftime("%Y-%m-%d")
        t_raw = str(time_str or "").strip()
        hour = current_dt.hour
        if t_raw:
            m = re.search(r"^([01]?\d|2[0-3])[:：]([0-5]?\d)$", t_raw)
            if m:
                hour = int(m.group(1))
        # 熬夜场景：凌晨0-9点的睡眠记录归到前一天
        # 这样用户凌晨1点、2点、...、8点睡觉都会记录为"昨晚"
        # 9点之后睡觉则认为是白天补觉或特殊作息，记录到当天
        if 0 <= hour < 9:
            return (current_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        return target

    def update_sleep_cycle(
        self,
        sleep_time: Optional[str] = None,
        wakeup_time: Optional[str] = None,
        target_date: Optional[str] = None,
    ) -> str:
        """显式修改指定日期的 sleep_cycle 字段（绕过 record_sleep 的保护逻辑）

        用于用户明确指出记录错误时，由 AI 主动调用此方法修正数据。
        不会触发"夜间睡眠被白天时间覆盖"的保护逻辑，因为这是用户明确要求的修改。

        Args:
            sleep_time: 睡觉时间（HH:MM），None 表示不修改 sleep 字段
            wakeup_time: 起床时间（HH:MM），None 表示不修改 wakeup 字段
            target_date: 指定日期（YYYY-MM-DD），None 表示自动判断：
                         - 若提供 sleep_time 则按熬夜规则归到前一天/当天
                         - 否则默认今天
        """
        if not sleep_time and not wakeup_time:
            return "未提供修改字段，sleep/wakeup 至少需要一个"

        # 解析目标日期
        if target_date:
            record_date = self._normalize_date(target_date)
        elif sleep_time:
            record_date = self._resolve_sleep_record_date(sleep_time)
        else:
            record_date = self._normalize_date()

        changed = []
        with self._with_record_lock(record_date):
            data = self._load_record(record_date)
            sc = data.get("sleep_cycle") or {}
            if not isinstance(sc, dict):
                sc = {"sleep": None, "wakeup": None, "duration": None}
            if sleep_time:
                sc["sleep"] = sleep_time
                sc["sleep_source"] = "user_manual"
                sc["sleep_recorded_at"] = now_str("%Y-%m-%dT%H:%M:%S%z")
                changed.append(f"sleep={sleep_time}")
            if wakeup_time:
                sc["wakeup"] = wakeup_time
                sc["wakeup_source"] = "user_manual"
                sc["wakeup_recorded_at"] = now_str("%Y-%m-%dT%H:%M:%S%z")
                changed.append(f"wakeup={wakeup_time}")
            data["sleep_cycle"] = sc
            self._update_sleep_cycle_duration(data)
            self._save_record(data, record_date)

        change_str = ", ".join(changed) if changed else "无变更"
        return f"已修正作息记录 ({record_date}): {change_str}"
