"""翻旧日记的跨天状态存储。

状态文件：``companion_data/{scope}_data/diary_reread_state.json``

记录每个角色「连续翻旧日记」的进度，供写日记时的概率加深与
「越翻越久远」偏置使用。读写全部异步，落盘走临时文件 + 原子替换。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import aiofiles

from core.utils.logger import get_logger

logger = get_logger("DiaryRereadStateStore")

STATE_FILENAME = "diary_reread_state.json"


@dataclass
class DiaryRereadState:
    """单个角色的翻旧日记状态。

    - last_roll_date: 最近一次掷概率的归属日（YYYY-MM-DD），当天只 roll 一次
    - last_reread_date: 最近一次真的翻了旧日记的归属日
    - streak: 连续翻旧的晚数（含最近一次），上限 MAX_STREAK
    - max_streak: 历史最大连续晚数
    - last_depth_days: 最近一次翻到多久之前（天）
    - total_count: 累计翻旧的晚数（同一天多次只计一次）
    """

    last_roll_date: str = ""
    last_reread_date: str = ""
    streak: int = 0
    max_streak: int = 0
    last_depth_days: int = 0
    total_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_roll_date": self.last_roll_date,
            "last_reread_date": self.last_reread_date,
            "streak": self.streak,
            "max_streak": self.max_streak,
            "last_depth_days": self.last_depth_days,
            "total_count": self.total_count,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "DiaryRereadState":
        raw = data if isinstance(data, dict) else {}

        def _int(value: Any) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0

        return cls(
            last_roll_date=str(raw.get("last_roll_date") or "").strip(),
            last_reread_date=str(raw.get("last_reread_date") or "").strip(),
            streak=max(0, _int(raw.get("streak"))),
            max_streak=max(0, _int(raw.get("max_streak"))),
            last_depth_days=max(0, _int(raw.get("last_depth_days"))),
            total_count=max(0, _int(raw.get("total_count"))),
        )

    def apply_reread(self, today: str, depth_days: Optional[int], max_streak: int) -> None:
        """登记一次「翻旧」事件（按归属日幂等，同日合并只更新深度）。

        - 与上次翻旧相隔一天 → streak +1（封顶 max_streak）
        - 中断 → streak 重置为 1
        - 同日重复 → 只把 last_depth_days 取最大，不重复计数
        """
        depth = max(0, int(depth_days or 0))
        if self.last_reread_date != today:
            if self.last_reread_date and self._is_previous_day(self.last_reread_date, today):
                self.streak = min(self.streak + 1, max_streak)
            else:
                self.streak = 1
            self.last_reread_date = today
            self.max_streak = max(self.max_streak, self.streak)
            self.total_count += 1
        if depth > self.last_depth_days:
            self.last_depth_days = depth

    @staticmethod
    def _is_previous_day(previous: str, today: str) -> bool:
        try:
            prev_dt = datetime.strptime(previous, "%Y-%m-%d")
            today_dt = datetime.strptime(today, "%Y-%m-%d")
        except (TypeError, ValueError):
            return False
        return (today_dt - prev_dt) == timedelta(days=1)


class DiaryRereadStateStore:
    """单个 scope 的翻旧状态持久化（异步、原子替换）。"""

    def __init__(self, scope: str, state_path: Optional[Path] = None):
        self._scope = str(scope or "").strip()
        self._state_path = state_path or self._default_path(self._scope)

    @staticmethod
    def _default_path(scope: str) -> Path:
        """``companion_data/{scope}_data/diary_reread_state.json``。"""
        try:
            from core.utils.data.data_paths import get_role_data_dir
            from core.utils.data.scope_registry import normalize_data_scope

            normalized = normalize_data_scope(scope, default="user")
            return get_role_data_dir(normalized) / STATE_FILENAME
        except Exception:  # noqa: BLE001 - 路径解析失败退到 user_data
            from core.utils.data_paths import get_user_data_dir

            return get_user_data_dir() / STATE_FILENAME

    @property
    def state_path(self) -> Path:
        return self._state_path

    async def load(self) -> DiaryRereadState:
        if not self._state_path.exists():
            return DiaryRereadState()
        try:
            async with aiofiles.open(self._state_path, "r", encoding="utf-8") as f:
                raw = json.loads(await f.read())
            return DiaryRereadState.from_dict(raw)
        except Exception as exc:  # noqa: BLE001 - 状态损坏不影响翻旧主流程
            logger.warning("读取翻旧状态失败 %s: %s", self._state_path, exc)
            return DiaryRereadState()

    async def save(self, state: DiaryRereadState) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._state_path.with_suffix(".tmp")
            async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(state.to_dict(), ensure_ascii=False, indent=2))
            tmp_path.replace(self._state_path)
        except Exception as exc:  # noqa: BLE001 - 落盘失败不阻断日记写入
            logger.warning("保存翻旧状态失败 %s: %s", self._state_path, exc)
