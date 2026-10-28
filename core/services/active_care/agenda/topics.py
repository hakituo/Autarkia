"""可带的话题：把今日推送排序结果整理成给决策模型挑的小菜单。

决策模型 send 时用 ``topic_id`` 指一条，下游据此：
- greeting：话题写进议程，主聊天里一步步带过去；
- direct：话题文本交给生成层，直接说出来。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

#: 菜单最多几条（排序里前几名就够，再多决策模型容易挑偏）
MENU_LIMIT = 3

#: 排序标题里给机器看的前缀，转成话题文本时去掉
_TITLE_PREFIXES = ("计划项：", "跟进任务：", "临近任务：", "学习复习提醒：", "和室友聊了：")


def build_topic_menu(ranked: Optional[Sequence[Any]], limit: int = MENU_LIMIT) -> List[Dict[str, str]]:
    """排序结果 → 菜单项 ``{id, title, detail, intent, reason}``（保持原排序）。"""
    menu: List[Dict[str, str]] = []
    for item in ranked or []:
        if not isinstance(item, Mapping):
            continue
        topic_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        if not topic_id or not title:
            continue
        menu.append(
            {
                "id": topic_id,
                "title": title,
                "detail": str(item.get("detail") or "").strip(),
                "intent": str(item.get("suggested_intent") or "").strip(),
                "reason": str(item.get("reason") or "").strip(),
            }
        )
        if len(menu) >= limit:
            break
    return menu


def find_topic(menu: Optional[Sequence[Any]], topic_id: Any) -> Optional[Dict[str, str]]:
    wanted = str(topic_id or "").strip()
    if not wanted:
        return None
    for item in menu or []:
        if isinstance(item, Mapping) and str(item.get("id") or "") == wanted:
            return dict(item)
    return None


def topic_text(item: Optional[Mapping[str, Any]]) -> str:
    """菜单项 → 一句人能看懂的话题（去掉机器前缀，附上细节）。"""
    if not item:
        return ""
    title = str(item.get("title") or "").strip()
    for prefix in _TITLE_PREFIXES:
        if title.startswith(prefix):
            title = title[len(prefix):].strip()
            break
    detail = str(item.get("detail") or "").strip()
    return f"{title}（{detail}）" if detail and detail not in title else title


def format_topic_menu(menu: Sequence[Mapping[str, Any]]) -> str:
    """给决策 prompt 用的菜单文本；菜单为空时返回空串。"""
    if not menu:
        return ""
    lines = ["【可带的话题】（send 时用 topic_id 选一条）"]
    for item in menu:
        lines.append(f"- topic_id={item.get('id')}：{topic_text(item)}")
    return "\n".join(lines)


__all__ = ["MENU_LIMIT", "build_topic_menu", "find_topic", "format_topic_menu", "topic_text"]
