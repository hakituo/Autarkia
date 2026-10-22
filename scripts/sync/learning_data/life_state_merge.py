"""角色作息 / 当日计划（``companion_data/character_daily/``）的合并策略。

``sleep_states.json`` 与 ``daily_state.json`` 都是「按角色各存一份当前状态」，
两端各写一份、内容必然不同，而 **mtime 完全不可比**：切换系统时，刚开机的一端
会拿「还没同步过来的旧状态」重新写一份，mtime 反而更新。

2026-10-16 实测：Linux 上角色 07:04 就醒了、跟用户聊了一整天，Windows 侧仍是
``phase=sleeping``；Windows 15:59 启动后把文件重写成 mtime 15:59（比 Linux 的
15:13 还新）。按 mtime 裁决就会把「还在睡」选走，于是程序刚启动就给用户发
「下午好。这下真睡多了，都四点才起」。

所以这里按状态里**内嵌的时间**判新旧，并且**按角色逐个合并**——同一个文件里
不同角色可能分别在两端推进，整文件二选一会把另一端的进度回退。

时间键 = ``(date, 子树里最大的 epoch 秒)``：

- ``date`` 是 ``YYYY-MM-DD``，字符串比较即时间顺序；
- epoch 秒只在 ``1e9 ~ 4e9``（2001~2096）区间内认，避免把时长 / 评分这类
  小数值误当时间戳。

输出统一用 ``\\n``：Windows 侧写出来的文件是 CRLF、Linux 侧是 LF，不统一的话
两端指纹永远不一致，每次同步都会白跑一次合并。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

#: 认作 epoch 秒的取值范围（约 2001-09 ~ 2096-10）
_EPOCH_MIN = 1_000_000_000.0
_EPOCH_MAX = 4_000_000_000.0

#: 顶层不是角色表时，往这些键下面找嵌套的角色表（``daily_state.json`` 的 plans）
_NESTED_ROLE_MAP_KEYS: Tuple[str, ...] = ("plans",)


def union_life_state(left: bytes, right: bytes) -> Optional[bytes]:
    """按角色合并两侧状态，每个角色取更新的那一份；解析失败返回 None。

    返回 None 表示「这份内容没法合并」，由调用方按普通冲突流程（mtime 裁决 +
    留冲突副本）处理，不会因为格式意外而把内容丢掉。
    """
    mine = _load(left)
    theirs = _load(right)
    if mine is None or theirs is None:
        return None
    merged = mine if mine == theirs else _merge(mine, theirs)
    return _canonical(merged)


def _merge(mine: Dict[str, Any], theirs: Dict[str, Any]) -> Dict[str, Any]:
    """两端形状一致且认得角色表时逐角色合并，否则整份取更新的。"""
    mine_map, mine_key = _locate_role_map(mine)
    theirs_map, theirs_key = _locate_role_map(theirs)
    if mine_map is None or theirs_map is None or mine_key != theirs_key:
        return _newer(mine, theirs)

    winner = _newer(mine, theirs)
    winner_map = mine_map if winner is mine else theirs_map
    loser_map = theirs_map if winner is mine else mine_map

    merged_map: Dict[str, Any] = {}
    # 按角色名排序遍历，保证合并结果与「先 A 后 B」还是「先 B 后 A」无关
    for role in sorted(set(loser_map) | set(winner_map)):
        older = loser_map.get(role)
        newer = winner_map.get(role)
        if older is None or newer is None:
            merged_map[role] = newer if older is None else older
        else:
            merged_map[role] = _newer(older, newer)

    merged = dict(winner)
    if mine_key is None:
        return merged_map
    merged[mine_key] = merged_map
    return merged


def _newer(first: Dict[str, Any], second: Dict[str, Any]) -> Dict[str, Any]:
    """取时间键更大的那份；并列时用规范化内容兜底，保证与合并顺序无关。"""
    key_first = _freshness(first)
    key_second = _freshness(second)
    if key_first != key_second:
        return first if key_first > key_second else second
    return first if _canonical(first) >= _canonical(second) else second


def _freshness(node: Any) -> Tuple[str, float]:
    """排序键：``date`` 越大越新；同日期再比子树里最大的 epoch 秒。"""
    return (_date_of(node), _max_epoch(node))


def _date_of(node: Any) -> str:
    """取 ``date`` 字段（``YYYY-MM-DD``，字符串比较即时间顺序）。"""
    if isinstance(node, dict):
        return str(node.get("date") or "").strip()
    return ""


def _max_epoch(node: Any) -> float:
    """子树里最大的「像 epoch 秒」的数值；不在合理区间的一律忽略。"""
    if isinstance(node, bool):
        return 0.0
    if isinstance(node, (int, float)):
        value = float(node)
        return value if _EPOCH_MIN <= value < _EPOCH_MAX else 0.0
    if isinstance(node, dict):
        return max((_max_epoch(value) for value in node.values()), default=0.0)
    if isinstance(node, list):
        return max((_max_epoch(value) for value in node), default=0.0)
    return 0.0


def _locate_role_map(
    payload: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """定位 ``{role_id: 状态}`` 映射，返回 ``(映射, 嵌套键)``。

    顶层所有值都是 dict 时视为顶层即角色表（``sleep_states.json``）；
    否则在 ``_NESTED_ROLE_MAP_KEYS`` 里找嵌套的那张表（``daily_state.json``）。
    ``嵌套键`` 为 None 表示角色表就是顶层。
    """
    if payload and all(isinstance(value, dict) for value in payload.values()):
        return payload, None
    for key in _NESTED_ROLE_MAP_KEYS:
        inner = payload.get(key)
        if isinstance(inner, dict) and inner:
            if all(isinstance(value, dict) for value in inner.values()):
                return inner, key
    return None, None


def _load(raw: bytes) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _canonical(payload: Dict[str, Any]) -> bytes:
    """规范化输出：两空格缩进、``\\n`` 换行，两端写出来完全一致。"""
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    return text.replace("\r\n", "\n").encode("utf-8") + b"\n"
