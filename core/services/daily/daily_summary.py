"""用户今日画像的渲染与作息规律推断（从 manager.py 拆出的 SummaryMixin）。

职责：把当天记录渲染成给模型看的【用户今日画像】，以及从近 N 天记录里推断作息规律。

⚠️ `get_today_summary` 需要门面里的 `render_device_sleep_line` 与
`split_health_entries`：测试会 patch `manager.get_current_time` /
`manager.render_device_sleep_line`，只有从门面取名才能命中 patch，
所以这两个助手留在门面，这里用**函数体内惰性 import** 取（同时避免模块级循环）。

拆分口径见 manager.py 的模块 docstring。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from core.utils.logger import get_logger

logger = get_logger("DAILY_MANAGER")


class SummaryMixin:
    """今日画像渲染与作息规律推断。"""

    def _infer_schedule_pattern(self, days: int = 7) -> str:
        """从最近几天的记录推断作息规律（中位数+范围）"""
        today = self._normalize_date()
        today_dt = datetime.strptime(today, "%Y-%m-%d")
        wakeups = []
        sleeps = []
        for i in range(1, days + 1):
            past_dt = today_dt - timedelta(days=i)
            past_str = past_dt.strftime("%Y-%m-%d")
            data = self._load_record(past_str)
            # 兼容新旧格式
            sc = data.get("sleep_cycle") or data.get("schedule") or {}
            w = sc.get("wakeup")
            s = sc.get("sleep")
            if w:
                wakeups.append((past_str, w))
            if s:
                sleeps.append((past_str, s))
        parts = []
        if wakeups:
            times = [t for _, t in wakeups]
            median = self._time_median(times)
            time_range = self._time_range(times)
            parts.append(f"用户通常起床: {median}{time_range}")
        if sleeps:
            times = [t for _, t in sleeps]
            median = self._time_median(times)
            time_range = self._time_range(times)
            # 这里刻意用「入睡」而不是「睡觉」：_extract_known_sleep_time_fact 会用
            # “昨晚睡觉/睡觉: HH:MM” 正则抽取“当天确切就寝事实”，中位数不能冒充它。
            parts.append(f"用户通常入睡: {median}{time_range}")
        if not parts:
            return ""
        return "【用户作息规律】" + "；".join(parts) + "（仅供参考，不是今天的实际时间）"

    @staticmethod
    def _time_to_minutes(time_str: str) -> int:
        """将 HH:MM 转换为从0点开始的分钟数，处理跨天（凌晨睡觉+24h）"""
        try:
            parts = time_str.split(":")
            h, m = int(parts[0]), int(parts[1])
            return h * 60 + m
        except (ValueError, IndexError):
            return 0

    @staticmethod
    def _minutes_to_time(minutes: int) -> str:
        """将分钟数转换回 HH:MM 格式"""
        minutes = minutes % (24 * 60)
        h = minutes // 60
        m = minutes % 60
        return f"{h:02d}:{m:02d}"

    def _time_median(self, times: list) -> str:
        """计算时间列表的中位数"""
        if not times:
            return ""
        minutes_list = [self._time_to_minutes(t) for t in times]
        # 对睡觉时间，如果跨越0点（如23:30, 00:30, 01:00），需要归一化
        # 简单处理：如果大部分值>12:00但有少量<6:00，将<6:00的+24h
        has_late = sum(1 for m in minutes_list if m > 12 * 60) > len(minutes_list) // 2
        if has_late:
            normalized = [m + 24 * 60 if m < 6 * 60 else m for m in minutes_list]
        else:
            normalized = minutes_list
        normalized.sort()
        n = len(normalized)
        mid = normalized[n // 2] if n % 2 == 1 else (normalized[n // 2 - 1] + normalized[n // 2]) // 2
        return self._minutes_to_time(mid)

    def _time_range(self, times: list) -> str:
        """计算时间列表的范围（最早-最晚）"""
        if len(times) < 2:
            return ""
        minutes_list = [self._time_to_minutes(t) for t in times]
        has_late = sum(1 for m in minutes_list if m > 12 * 60) > len(minutes_list) // 2
        if has_late:
            normalized = [m + 24 * 60 if m < 6 * 60 else m for m in minutes_list]
        else:
            normalized = minutes_list
        min_val = min(normalized)
        max_val = max(normalized)
        return f"（{self._minutes_to_time(min_val)}~{self._minutes_to_time(max_val)}）"

    def get_today_summary(self) -> str:
        """获取用户今日画像摘要，用于 System Prompt。

        归属约定（2026-09-17）：本摘要描述的是**用户**，不是角色本人。
        每一行都必须带「用户」前缀，标题也必须写明是用户画像——
        否则角色会把自己的作息和用户的混在一起（用户起床后角色自称「刚睡醒」）。
        """
        # 这两个助手留在门面：测试会 patch manager.render_device_sleep_line /
        # manager.get_current_time，只有从门面取名才命中。惰性 import 同时避免模块级循环。
        from core.services.daily.manager import (
            render_device_sleep_line,
            split_health_entries,
        )
        today = self._normalize_date()
        data = self._load_record(today)
        lines = ["【用户今日画像】"]

        sc = data.get("sleep_cycle", {})
        wakeup = sc.get("wakeup")
        sleep = sc.get("sleep")
        duration = sc.get("duration")
        has_schedule = bool(wakeup or sleep)

        if sleep and wakeup:
            duration_str = f" ({duration})" if duration else ""
            lines.append(f"- 用户睡眠: {sleep} → {wakeup}{duration_str}")
        elif wakeup:
            lines.append(f"- 用户起床: {wakeup}")
        elif sleep:
            lines.append(f"- 用户睡眠: {sleep}")
        else:
            # Try to get sleep from previous day
            prev_date = self._get_previous_date(today)
            prev_data = self._load_record(prev_date)
            prev_sc = prev_data.get("sleep_cycle") or {}
            prev_sleep = prev_sc.get("sleep")
            if prev_sleep:
                lines.append(f"- 用户昨晚睡觉: {prev_sleep}")

        # 设备实测睡眠事实（只读健康快照）。三星睡眠只在睡醒事件到达时写进
        # 日记录，聊天侧又不直读快照；不补这一行，设备上已有的睡眠区间对
        # 角色就是完全不可见的（2026-09-18 修）。
        device_sleep_line = render_device_sleep_line()
        if device_sleep_line:
            lines.append(device_sleep_line)

        if not has_schedule:
            pattern = self._infer_schedule_pattern()
            if pattern:
                lines.append(pattern)

        meals = data.get("meals", [])
        if meals:
            food_items = []
            drink_total = 0
            for m in meals:
                if m.get("type") == "drink":
                    match = re.search(r"(\d+)", str(m.get("content") or ""))
                    if match:
                        drink_total += int(match.group(1))
                else:
                    food_items.append(f"{m['type']}({m['content']})")

            meal_str = ", ".join(food_items) if food_items else "无正餐记录"
            if drink_total > 0:
                meal_str += f"; 饮水: {drink_total}ml"

            lines.append(f"- 用户三餐: {meal_str}")
        else:
            lines.append("- 用户三餐: 无记录")

        study = data.get("study", {}).get("sessions", [])
        if study:
            topics = set([s["topic"] for s in study])
            lines.append(f"- 用户学习: {', '.join(topics)} ({len(study)} 次)")

        acts = data.get("activities", [])
        if acts:
            act_strs = [f"{a['content']}" for a in acts]
            lines.append(f"- 用户活动: {', '.join(act_strs)}")

        health = data.get("health", [])
        if health:
            fresh_health, earlier_health = split_health_entries(health)
            if fresh_health:
                lines.append(f"- 用户健康: {', '.join(fresh_health)}")
            if earlier_health:
                lines.append(
                    f"- 用户健康（较早记录，可能已缓解）: {', '.join(earlier_health)}"
                )
                lines.append(
                    "- 用户健康时效说明：标「较早记录」的是当天早些时候记的，"
                    "不代表他现在还在难受；除非他本人再提起，不要据此询问病情。"
                )

        mood = data.get("mood")
        if mood:
            if isinstance(mood, dict):
                lines.append(f"- 用户心情: {mood.get('mood')} ({mood.get('detail', '')})")
            else:
                lines.append(f"- 用户心情: {mood}")

        return "\n".join(lines)
