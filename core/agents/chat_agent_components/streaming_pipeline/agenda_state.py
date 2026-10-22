"""议程注入的「当日状态」持久化（从 agenda_injections 拆出）。

【为什么拆】
agenda_injections 原本一个文件里同时管「决定注入什么」（阶梯 + 竞争）和
「记住已经注入过什么」（当日状态文件）。2026-10-02 加闲聊计数后它涨到 420 行，
越过 300 行门禁（`tests/scripts/docs/check_file_sizes.py` 会当场判 FAIL）。
这里只搬走持久化这一层，不改任何语义。

【存什么】
落在当日目录下的 ``agenda_injected.json``，按会话隔离：

``{<会话>: {"injected": ["today_plan", ...], "chitchat_streak": N}}``

- ``injected``：当天已经注入过的条目名（once_per_day 节流用）；
- ``chitchat_streak``：连续「什么都没注入」的纯闲聊轮数（闲聊门控用）。

【兼容】
2026-10-02 之前的格式是 ``{<会话>: ["today_plan", ...]}``（值是列表，没有计数）。
读到列表时按「已注入名单 + 计数 0」解释，老文件不会被当成损坏。

【线程约定】
本模块全部是同步 IO，调用方负责 ``asyncio.to_thread``。
"""

from __future__ import annotations

from typing import Any


def _marker_path(user_id: str, date_str: str):
    """当日议程状态文件路径（按会话隔离，落在当日目录下）。"""
    from core.utils.data_paths import get_user_data_dir

    return (
        get_user_data_dir() / "daily"
        / date_str[0:4] / date_str[5:7] / date_str[8:10]
        / "agenda_injected.json"
    )


def _safe_int(value: Any) -> int:
    """把脏值压成非负整数；bool 不算数。"""
    try:
        if isinstance(value, bool):
            return 0
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _read_state(user_id: str, date_str: str) -> dict:
    """同步读当日状态（调用方负责 to_thread）。读不到一律当空。"""
    import json

    empty = {"injected": [], "chitchat_streak": 0}
    try:
        path = _marker_path(user_id, date_str)
        if not path.exists():
            return empty
        payload = json.loads(path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            return empty
        raw = payload.get(str(user_id))
        if isinstance(raw, list):
            # 旧格式：值是「已注入名单」列表，没有闲聊计数
            return {"injected": [str(n) for n in raw], "chitchat_streak": 0}
        if isinstance(raw, dict):
            return {
                "injected": [str(n) for n in (raw.get("injected") or [])],
                "chitchat_streak": _safe_int(raw.get("chitchat_streak")),
            }
        return empty
    except Exception:
        return empty


def _write_state(user_id: str, date_str: str, state: dict) -> None:
    """同步写当日状态（调用方负责 to_thread）。失败只记日志，不影响本轮注入。"""
    import json

    from core.utils.logger import get_logger

    try:
        path = _marker_path(user_id, date_str)
        payload = {}
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8")) or {}
            if not isinstance(payload, dict):
                payload = {}
        payload[str(user_id)] = {
            "injected": [str(n) for n in (state.get("injected") or [])],
            "chitchat_streak": _safe_int(state.get("chitchat_streak")),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:  # noqa: BLE001
        get_logger("ChatAgent").debug("写议程状态失败（不影响本轮）：%s", e)


def _already_injected(user_id: str, name: str, date_str: str) -> bool:
    """同步读标记（调用方负责 to_thread）。读不到一律当「没注入过」。"""
    return name in set(_read_state(user_id, date_str).get("injected") or [])


def _mark_injected(user_id: str, name: str, date_str: str) -> None:
    """同步写标记（调用方负责 to_thread）。失败只记日志，不影响本轮注入。"""
    state = _read_state(user_id, date_str)
    names = list(state.get("injected") or [])
    if name not in names:
        names.append(name)
    state["injected"] = names
    _write_state(user_id, date_str, state)


def _get_chitchat_streak(user_id: str, date_str: str) -> int:
    """连续纯闲聊轮数（调用方负责 to_thread）。"""
    return _safe_int(_read_state(user_id, date_str).get("chitchat_streak"))


def _bump_chitchat_streak(user_id: str, date_str: str) -> int:
    """本轮没注入任何议程 → 闲聊计数 +1。返回新值。"""
    state = _read_state(user_id, date_str)
    state["chitchat_streak"] = _safe_int(state.get("chitchat_streak")) + 1
    _write_state(user_id, date_str, state)
    return state["chitchat_streak"]


def _reset_chitchat_streak(user_id: str, date_str: str) -> None:
    """真的催过一次 → 计数归零，重新开始数。"""
    state = _read_state(user_id, date_str)
    if _safe_int(state.get("chitchat_streak")):
        state["chitchat_streak"] = 0
        _write_state(user_id, date_str, state)
