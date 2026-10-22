"""饮食 / 饮水 / 学习 / 活动 / 健康 / 心情的记录入口（从 manager.py 拆出的 EntriesMixin）。

这一层只负责「把一件事追加进当天的记录」，时效判定与渲染在 daily_summary。

拆分口径见 manager.py 的模块 docstring。
"""

from __future__ import annotations

from typing import Optional

from core.utils.logger import get_logger
from core.utils.time_utils import now_str

logger = get_logger("DAILY_MANAGER")


class EntriesMixin:
    """各类日常记录的写入入口。"""

    def record_meal(self, meal_type: str, content: str):
        """记录饮食"""
        with self._with_record_lock():
            data = self._load_record()
            timestamp = now_str("%H:%M")
            data["meals"].append(
                {"type": meal_type, "content": content, "time": timestamp}
            )
            self._save_record(data)
        return f"已记录饮食: {meal_type} - {content}"

    def upsert_meal(self, meal_type: str, content: str, time_str: Optional[str] = None):
        with self._with_record_lock():
            data = self._load_record()
            timestamp = str(time_str or now_str("%H:%M")).strip()
            meal_t = str(meal_type or "meal").strip() or "meal"
            payload = {
                "type": meal_t,
                "content": str(content or "").strip(),
                "time": timestamp
            }
            meals = data.get("meals")
            if not isinstance(meals, list):
                meals = []
                data["meals"] = meals
            replaced = False
            for idx in range(len(meals) - 1, -1, -1):
                item = meals[idx]
                if not isinstance(item, dict):
                    continue
                if str(item.get("type") or "").strip() == meal_t:
                    meals[idx] = payload
                    replaced = True
                    break
            if not replaced:
                meals.append(payload)
            self._save_record(data)
        return f"已校正饮食: {meal_t} - {payload['content']}"

    def record_drink(self, drink_type: str, content: str):
        """记录喝水"""
        with self._with_record_lock():
            data = self._load_record()
            timestamp = now_str("%H:%M")
            data["meals"].append(
                {"type": drink_type, "content": content, "time": timestamp}
            )
            self._save_record(data)
        return f"已记录饮品: {content}"

    def record_study(
        self,
        topic: str,
        content: str,
        *,
        session_id: Optional[str] = None,
        minutes: Optional[int] = None,
        count_in_total: bool = True,
        source: Optional[str] = None,
    ):
        """记录学习。

        ``session_id`` 非空时按 id 覆盖同一条记录，供客户端计时器反复上报
        「截至目前的累计时长」——重复上报只替换，不叠加。``minutes`` 是显式
        时长字段，优先于正文里的「N 分钟」；``count_in_total=False`` 表示这条
        只作上下文留存，不计入今日学习时长。
        """
        with self._with_record_lock():
            data = self._load_record()
            timestamp = now_str("%H:%M")
            entry = {"topic": topic, "content": content, "time": timestamp}
            if session_id:
                entry["id"] = str(session_id)
            if minutes is not None:
                entry["minutes"] = max(0, int(minutes))
            if not count_in_total:
                entry["count_in_total"] = False
            if source:
                entry["source"] = str(source)

            sessions = data["study"]["sessions"]
            replaced = False
            if session_id:
                for index, existing in enumerate(sessions):
                    if not isinstance(existing, dict):
                        continue
                    if str(existing.get("id") or "") != entry["id"]:
                        continue
                    # 首次记录的时刻更接近「什么时候开始学的」，覆盖时保留
                    entry["time"] = str(existing.get("time") or timestamp)
                    sessions[index] = entry
                    replaced = True
                    break
            if not replaced:
                sessions.append(entry)
            self._save_record(data)
        return f"已记录学习: {topic}"

    def record_activity(self, activity_type: str, content: str):
        """记录其他活动（游戏、娱乐、杂事）"""
        with self._with_record_lock():
            data = self._load_record()
            timestamp = now_str("%H:%M")
            data["activities"].append(
                {"type": activity_type, "content": content, "time": timestamp}
            )
            self._save_record(data)
        return f"已记录活动: {content}"

    def record_health(self, symptom: str, detail: str = ""):
        """记录健康状态"""
        with self._with_record_lock():
            data = self._load_record()
            timestamp = now_str("%H:%M")
            if "health" not in data:
                data["health"] = []
            data["health"].append(
                {"symptom": symptom, "detail": detail, "time": timestamp}
            )
            self._save_record(data)
        return f"已记录健康状态: {symptom}"

    def record_mood(self, mood: str, detail: str = ""):
        """记录心情"""
        with self._with_record_lock():
            data = self._load_record()
            timestamp = now_str("%H:%M")
            data["mood"] = {"mood": mood, "detail": detail, "time": timestamp}
            self._save_record(data)
        return f"已记录心情: {mood}"
