"""用户每日生活画像（User Portrait）的读写与渲染入口。
数据在 `companion_data/user_data/daily_records/YYYY/M/D/daily_record.json`。
【拆分说明（2026-10-02）】原 862 行拆成薄壳门面 + 4 个 mixin 子模块：
``daily_record_store`` / ``daily_sleep`` / ``daily_entries`` / ``daily_summary``；
用到「会被测试 patch 的全局名」的成员留在门面（详见当日更新日志）。
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Optional, Iterator
from core.utils.logger import get_logger
from core.utils.singleton import SingletonFactory
from core.utils.data_paths import get_user_daily_records_dir
from core.utils.time_utils import get_current_time, now_str, today_str

try:
    from filelock import FileLock, Timeout as FileLockTimeout
except ImportError:  # pragma: no cover - filelock 是项目依赖
    FileLock = None  # type: ignore[misc,assignment]
    FileLockTimeout = Exception  # type: ignore[misc,assignment]

from core.services.daily.daily_entries import EntriesMixin
from core.services.daily.daily_record_store import RecordStoreMixin
from core.services.daily.daily_sleep import SleepMixin
from core.services.daily.daily_summary import SummaryMixin

logger = get_logger("DAILY_MANAGER")

# 健康症状是瞬时事件：凌晨 0 点记下的「恶心」，到晚上 19 点不该被当成
# 「他现在还在难受」。因此渲染画像时补上记录时刻，并按时效标注新鲜度：
# 窗口内视为当前状态，超窗的单独归为「较早记录，可能已缓解」。
HEALTH_FRESH_WINDOW_HOURS = 6
# 设备实测睡眠行只在快照足够新时展示：超过该窗口说明很久没同步，
# 再展示会把几天前的作息当成当下的（同理，快照时间超前也不展示）。
DEVICE_SLEEP_FACT_MAX_AGE_HOURS = 72
_HEALTH_CLOCK_RE = re.compile(r"^\s*(\d{1,2})\s*[:：]\s*(\d{2})\s*$")


def _parse_health_clock_minutes(value: Any) -> Optional[int]:
    """把 'HH:MM' 解析成当天分钟数；无法解析时返回 None。"""
    match = _HEALTH_CLOCK_RE.match(str(value or ""))
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def split_health_entries(health: Any, now: Optional[datetime] = None) -> tuple:
    """把 health 记录按新鲜度拆成「当前」与「较早」两组文本片段。

    返回 (fresh_parts, earlier_parts)，两组都是已带时刻/时长标注的字符串列表；
    没有可渲染内容时返回 ([], [])。HEALTH_FRESH_WINDOW_HOURS 以内的记录
    视为当前状态（只附记录时刻），更早的记录标出距现在的小时数。
    标签由各调用方自己拼，这里只负责时效判定与文本片段。
    """
    entries = [item for item in (health or []) if isinstance(item, dict)]
    if not entries:
        return [], []

    current = now or get_current_time()
    now_minutes = current.hour * 60 + current.minute
    fresh: list = []
    earlier: list = []

    for item in entries:
        symptom = str(item.get("symptom") or "").strip()
        if not symptom:
            continue
        raw_time = str(item.get("time") or "").strip()
        minutes = _parse_health_clock_minutes(raw_time)
        if minutes is None:
            # 没有可用时刻，按当前状态呈现，避免把症状整个吞掉
            fresh.append(symptom)
            continue
        age_minutes = now_minutes - minutes
        if age_minutes < 0:
            # 记录时刻晚于当前：跨零点或时钟漂移，按刚记录处理
            age_minutes += 24 * 60
        if age_minutes <= HEALTH_FRESH_WINDOW_HOURS * 60:
            fresh.append(f"{symptom}（{raw_time}）")
        else:
            earlier.append(f"{symptom}（{raw_time}，约{age_minutes // 60}小时前）")

    return fresh, earlier


class DailyActivityManager(RecordStoreMixin, SleepMixin, EntriesMixin, SummaryMixin):
    """
    管理用户每日的生活画像（User Portrait）。
    数据存储在 companion_data/user_data/daily_records/YYYY/M/D/daily_record.json
    """

    # 起床时间可能同时来自聊天推断、用户明说和健康设备。
    # 数值越大越可靠，低优先级来源不得覆盖高优先级数据。
    WAKEUP_SOURCE_PRIORITIES = {
        "legacy": 0,
        "chat_inferred": 10,
        "chat_explicit_time": 30,
        "active_care_session": 40,
        "samsung_health": 80,
        "user_manual": 100,
    }

    def __init__(self):
        self.root_dir = str(get_user_daily_records_dir())
        os.makedirs(self.root_dir, exist_ok=True)

    def _normalize_date(self, date_str: Optional[str] = None) -> str:
        """解析日期字符串；未提供时默认"自然日今天"。

        注意：daily_record 是实时事件流水（饮食/学习/健康等），必须按自然日归属，
        不能用 get_diary_target_date_str()（其凌晨归属会覆盖到昨天——那是日记的
        归属语义）。睡眠/起床记录的跨天归属由 _resolve_sleep_record_date 单独处理。
        """
        raw = (date_str or "").strip()
        if not raw:
            return today_str()
        try:
            return datetime.strptime(raw, "%Y-%m-%d").strftime("%Y-%m-%d")
        except Exception:
            return today_str()

    @contextmanager
    def _with_record_lock(
        self, date_str: Optional[str] = None, timeout: float = 10.0
    ) -> Iterator[None]:
        """对指定日期的记录加文件锁，保护 read-modify-write 操作的原子性。

        跨进程互斥：即使有多个 Python 进程同时写同一天的记录，
        也会通过 .lock 文件串行化，避免读后写导致的数据覆盖。

        若 filelock 未安装，则退化为无锁模式（仅记录 warning），不阻塞业务流程。
        """
        normalized = self._normalize_date(date_str)
        if FileLock is None:
            logger.warning(
                "filelock 未安装，daily record 写入无跨进程锁保护 (date=%s)",
                normalized,
            )
            yield
            return

        lock_path = self._get_lock_path(normalized)
        # 确保锁文件所在目录存在
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        lock = FileLock(lock_path, timeout=timeout)
        try:
            with lock:
                yield
        except FileLockTimeout:
            logger.error(
                "获取 daily record 文件锁超时 (date=%s, timeout=%ss)",
                normalized,
                timeout,
            )
            raise
        except Exception:
            raise

    def record_sleep(
        self,
        time_str: Optional[str] = None,
        now_dt: Optional[datetime] = None,
        target_date: Optional[str] = None,
        *,
        source: Optional[str] = None,
        force: bool = False,
    ):
        """记录睡觉时间，并按来源可靠性防止聊天覆盖健康设备。
        
        Args:
            time_str: 时间字符串，如 "22:30"
            now_dt: 当前时间（用于测试）
            target_date: 指定日期，如 "2026-04-07"。如果不指定，则根据时间自动判断
        """
        if not time_str:
            time_str = (now_dt or get_current_time()).strftime("%H:%M")
        if target_date:
            record_date = target_date
        else:
            record_date = self._resolve_sleep_record_date(time_str, now_dt=now_dt)
        normalized_source = str(source or "chat_explicit_time").strip() or "chat_explicit_time"
        incoming_priority = self.WAKEUP_SOURCE_PRIORITIES.get(normalized_source, 0)
        with self._with_record_lock(record_date):
            data = self._load_record(record_date)
            sleep_cycle = data.get("sleep_cycle") or {}
            existing_sleep = sleep_cycle.get("sleep")
            existing_source = str(sleep_cycle.get("sleep_source") or "legacy")
            existing_priority = self.WAKEUP_SOURCE_PRIORITIES.get(existing_source, 0)
            if existing_sleep and not force and existing_priority > incoming_priority:
                return f"Kept existing sleep: {existing_sleep} ({existing_source})"
            if existing_sleep and not force and existing_sleep != time_str:
                try:
                    exist_h = int(existing_sleep.split(":")[0])
                    new_h = int(time_str.split(":")[0])
                    # 保护逻辑：已有的睡觉时间在晚上/凌晨（18-9点），新值在白天（5-10点）
                    # 这可能是误识别的起床时间覆盖了睡觉时间
                    is_existing_night_sleep = 18 <= exist_h <= 23 or 0 <= exist_h < 9
                    is_new_suspicious_daytime = 5 <= new_h < 10
                    if is_existing_night_sleep and is_new_suspicious_daytime:
                        return f"Kept existing sleep time: {existing_sleep} (ignored suspicious daytime value {time_str})"
                except (ValueError, IndexError):
                    pass
            data["sleep_cycle"]["sleep"] = time_str
            data["sleep_cycle"]["sleep_source"] = normalized_source
            data["sleep_cycle"]["sleep_recorded_at"] = now_str("%Y-%m-%dT%H:%M:%S%z")
            self._update_sleep_cycle_duration(data)
            self._save_record(data, record_date)
        return f"Recorded sleep: {time_str} ({normalized_source}, {record_date})"


def render_device_sleep_line() -> str:
    """渲染「设备实测睡眠」行（只读健康快照，不写日记录）。

    动机（2026-09-18）：三星睡眠只在睡醒事件到达时才同步进日记录，聊天侧又
    从不直接读健康快照；一旦事件没落地（还在睡 / sleep_end_time 没变化），
    设备上明明有睡眠区间，角色也完全看不到。这里补一条只读事实，并显式标注
    来源，避免和聊天推断出来的作息混在一起。

    时间口径：快照是 UTC ISO，这里统一转本地时区后再渲染；
    跨天睡眠带上日期前缀，避免被误读成「今天/昨晚」。
    """
    try:
        from core.services.health_sync.store import read_latest_sleep_window

        window = read_latest_sleep_window()
        if not window:
            return ""
        start = window["start"]
        end = window["end"]
        now = get_current_time()
        age_hours = (now - end).total_seconds() / 3600.0
        # 快照里挂着的是「最近一次同步到的睡眠」：太久没同步（或时间超前）时
        # 说明这条不是当下的作息，宁可不说，也不要把几天前的数据当成昨晚。
        if age_hours > DEVICE_SLEEP_FACT_MAX_AGE_HOURS or age_hours < -1:
            return ""
        # 时长口径与日记录保持一致（入睡→起床的跨度）
        span_minutes = int(round((end - start).total_seconds() / 60.0))
        hours, mins = divmod(max(0, span_minutes), 60)
        duration = f"{hours}h{mins}m" if hours else f"{mins}m"
        # 设备口径的「实际睡着」通常短于卧床跨度（含中途清醒），明确写出来，
        # 避免用户问「睡了多久」时被跨度误导。单个脏字段不该拖垮整行。
        try:
            reported_minutes = int(round(float(window.get("sleep_minutes"))))
        except (TypeError, ValueError):
            reported_minutes = 0
        if 0 < reported_minutes < span_minutes:
            rh, rm = divmod(reported_minutes, 60)
            duration += f"，实际睡眠 {rh}h{rm}m"
        score = window.get("sleep_score")
        if score is not None:
            try:
                duration += f"，得分 {int(round(float(score)))}"
            except (TypeError, ValueError):
                pass
        same_day = start.date() == end.date()
        start_text = start.strftime("%m-%d %H:%M")
        end_text = end.strftime("%H:%M") if same_day else end.strftime("%m-%d %H:%M")
        # 2026-10-02 去掉原句尾的「优先于聊天推断」。
        # 那五个字等于告诉模型「设备记录压过主人自己说的话」，实测后果：主人明确说过
        # 「我是睡到现在、手表半夜摘了」，角色仍按 03:03 反复追问（07:27 → 13:37）。
        # 设备只记到摘表那一刻，本来就可能不完整，没有资格压过本人陈述；
        # 这里改成中性的来源标注 + 不完整提示，由模型按上下文自行取舍。
        return (
            f"- 用户睡眠（三星健康实测，可能因摘表/未同步而不完整）: "
            f"{start_text} → {end_text}（{duration}）"
        )
    except Exception as e:
        logger.warning("渲染设备睡眠事实失败: %s", e)
        return ""


_daily_manager_factory = SingletonFactory(DailyActivityManager)


def get_daily_manager():
    return _daily_manager_factory.get()
