"""每日记录的读写与规范化（从 manager.py 拆出的 RecordStoreMixin）。

职责：记录文件的路径推导、跨进程文件锁、加载/规范化/保存。
不碰睡眠语义（见 daily_sleep）、不碰渲染（见 daily_summary）。

拆分口径见 manager.py 的模块 docstring。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

logger = get_logger("DAILY_MANAGER")


class RecordStoreMixin:
    """记录读写：路径 / 锁 / 加载 / 规范化 / 保存。"""

    def _get_legacy_file_path(self, date_str: str) -> str:
        return os.path.join(self.root_dir, f"{date_str}.json")

    def _get_previous_month_path(self, date_str: str) -> str:
        return os.path.join(
            self.root_dir, date_str[:4], date_str[5:7], f"{date_str}.json"
        )

    def _get_file_path(self, date_str: Optional[str] = None) -> str:
        normalized = self._normalize_date(date_str)
        year, month, day = normalized.split("-")
        day_dir = os.path.join(
            self.root_dir, str(int(year)), str(int(month)), str(int(day))
        )
        os.makedirs(day_dir, exist_ok=True)
        return os.path.join(day_dir, "daily_record.json")

    def _get_lock_path(self, date_str: str) -> str:
        """获取指定日期记录文件对应的跨平台文件锁路径。

        锁文件与 daily_record.json 同目录，名为 daily_record.lock。
        使用 filelock 库实现 Windows/Linux 通用互斥。
        """
        record_path = self._get_file_path(date_str)
        return record_path + ".lock"

    def _get_previous_date(self, date_str: str) -> str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            dt = get_current_time()
        return (dt - timedelta(days=1)).strftime("%Y-%m-%d")

    def _default_record(self, normalized: str) -> Dict[str, Any]:
        return {
            "date": normalized,
            "sleep_cycle": {
                "sleep": None,
                "wakeup": None,
                "duration": None,
                "sleep_source": None,
                "sleep_recorded_at": None,
                "wakeup_source": None,
                "wakeup_recorded_at": None,
            },
            "meals": [],
            "study": {"sessions": [], "summary": ""},
            "activities": [],
            "summary": "",
        }

    def _normalize_record(self, data: Dict[str, Any], date_str: str) -> Dict[str, Any]:
        normalized = dict(data or {})
        normalized["date"] = self._normalize_date(normalized.get("date") or date_str)
        
        # 兼容旧格式 schedule -> 新格式 sleep_cycle
        if "schedule" in normalized and "sleep_cycle" not in normalized:
            schedule = normalized.pop("schedule")
            if isinstance(schedule, dict):
                normalized["sleep_cycle"] = {
                    "sleep": schedule.get("sleep"),
                    "wakeup": schedule.get("wakeup"),
                    "duration": None,
                    "sleep_source": None,
                    "sleep_recorded_at": None,
                    "wakeup_source": None,
                    "wakeup_recorded_at": None,
                }
            else:
                normalized["sleep_cycle"] = self._default_record(date_str)["sleep_cycle"]
        elif "sleep_cycle" not in normalized:
            normalized["sleep_cycle"] = self._default_record(date_str)["sleep_cycle"]
        else:
            sc = normalized["sleep_cycle"]
            if not isinstance(sc, dict):
                normalized["sleep_cycle"] = self._default_record(date_str)["sleep_cycle"]
            else:
                normalized["sleep_cycle"] = {
                    "sleep": sc.get("sleep"),
                    "wakeup": sc.get("wakeup"),
                    "duration": sc.get("duration"),
                    "sleep_source": sc.get("sleep_source"),
                    "sleep_recorded_at": sc.get("sleep_recorded_at"),
                    "wakeup_source": sc.get("wakeup_source"),
                    "wakeup_recorded_at": sc.get("wakeup_recorded_at"),
                }
        
        if not isinstance(normalized.get("meals"), list):
            normalized["meals"] = []
        study = normalized.get("study")
        if not isinstance(study, dict):
            study = {}
        sessions = study.get("sessions")
        if not isinstance(sessions, list):
            sessions = []
        normalized["study"] = {
            "sessions": sessions,
            "summary": study.get("summary", "")
        }
        if not isinstance(normalized.get("activities"), list):
            normalized["activities"] = []
        if "health" in normalized and not isinstance(normalized.get("health"), list):
            normalized["health"] = []
        if (
            "mood" in normalized
            and normalized.get("mood") is not None
            and not isinstance(normalized.get("mood"), (dict, str))
        ):
            normalized["mood"] = None
        if "summary" not in normalized:
            normalized["summary"] = ""
        return normalized

    def _compact_record(self, data: Dict[str, Any]) -> Dict[str, Any]:
        compacted = dict(data or {})
        if not compacted.get("health"):
            compacted.pop("health", None)
        if not compacted.get("mood"):
            compacted.pop("mood", None)
        if not str(compacted.get("summary") or "").strip():
            compacted.pop("summary", None)
        return compacted

    def _load_record(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        normalized = self._normalize_date(date_str)
        path = self._get_file_path(normalized)
        if not os.path.exists(path):
            previous_month_path = self._get_previous_month_path(normalized)
            if os.path.exists(previous_month_path):
                path = previous_month_path
        if not os.path.exists(path):
            legacy_path = self._get_legacy_file_path(normalized)
            if os.path.exists(legacy_path):
                path = legacy_path
        if not os.path.exists(path):
            return self._default_record(normalized)
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return self._normalize_record(raw, normalized)
        except Exception as e:
            logger.error(f"Failed to load daily record: {e}")
            return self._default_record(normalized)

    def get_record(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        """获取指定日期的完整记录"""
        return self._load_record(date_str)

    def _save_record(self, data: Dict[str, Any], date_str: Optional[str] = None):
        path = self._get_file_path(date_str)
        try:
            normalized = self._normalize_record(data, self._normalize_date(date_str))
            compacted = self._compact_record(normalized)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(compacted, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save daily record: {e}")
