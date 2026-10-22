"""QQ 收藏表情（NapCat mface 通道）。

NapCat 的 mface 消息段需要 ``emoji_id`` / ``emoji_package_id`` / ``key`` 三个
发送字段，它们只能来自 QQ 收藏表情库（``fetch_custom_face_detail`` 返回的
``md5`` / ``epId`` / ``resId``）。角色不能凭空拼一个商城表情，所以这里只做
一件事：**在本账号已收藏的表情里按 summary 匹配，命中才允许发送**；匹配不到
就返回 None，由调用方跳过，不影响文字回复。

配置见 ``config/yaml/qq_custom_faces.yaml``：

```yaml
faces:
  wow:
    summary: "哇"      # 与收藏表情的 desc 做包含匹配（忽略空白与方括号）
    roles: []          # 只有这些角色可以发；留空 = 不限制
```

历史背景：2026-08-23 曾因 ``fetch_custom_face_detail`` 字段误读
（按 emoji_id/emoji_package_id 取）导致始终取空，后按 NapCat 源码映射为
md5→emoji_id、epId→emoji_package_id、resId→key；当时收窄的是「上传通用表情包
再发送」的路径，本次只做「发已收藏的表情」，不涉及 add_custom_face。
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import yaml

from core.utils.common import get_project_root
from core.utils.logger import get_logger

logger = get_logger("qq_custom_face")

_CONFIG_PATH = (
    Path(get_project_root()) / "config" / "yaml" / "qq_custom_faces.yaml"
)

# 配置读取缓存：正常调参不需要立刻生效，30 秒足够
_CONFIG_TTL_SECONDS = 30.0
# 收藏表情可能很多（上限 500），一次取够，避免匹配不到
_FETCH_COUNT = 200

CallAction = Callable[[str, dict | None, float], Awaitable[tuple[int, Any]]]

_config_cache: dict[str, Any] = {"ts": 0.0, "faces": {}}
# (账号标识, 表情名) -> mface CQ 码；账号间必须隔离，否则贴纸字段串号
_face_cache: dict[tuple[str, str], str] = {}
# 解析失败后的冷却，避免每条回复都去拉一次收藏库、刷同一份 warning
_FAILURE_COOLDOWN_SECONDS = 60.0
_failure_until: dict[tuple[str, str], float] = {}


def _remember_failure(cache_key: tuple[str, str]) -> None:
    _face_cache[cache_key] = ""
    _failure_until[cache_key] = time.monotonic() + _FAILURE_COOLDOWN_SECONDS


def load_face_config() -> dict[str, dict[str, Any]]:
    """读取收藏表情配置（按 TTL 缓存）。"""
    now = time.monotonic()
    if now - float(_config_cache["ts"]) < _CONFIG_TTL_SECONDS:
        return _config_cache["faces"]

    faces: dict[str, dict[str, Any]] = {}
    try:
        if _CONFIG_PATH.exists():
            raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
            data = raw.get("faces") if isinstance(raw, dict) else {}
            if isinstance(data, dict):
                for name, entry in data.items():
                    key = str(name or "").strip().lower()
                    if key and isinstance(entry, dict):
                        faces[key] = entry
    except Exception as exc:  # noqa: BLE001 - 配置损坏不能让发送链路崩掉
        logger.warning("读取 qq_custom_faces.yaml 失败: %s", exc)

    _config_cache.update({"ts": now, "faces": faces})
    return faces


def _allowed_roles(entry: dict[str, Any]) -> set[str]:
    roles = entry.get("roles")
    if not isinstance(roles, (list, tuple, set)):
        return set()
    return {
        str(item or "").strip().lower()
        for item in roles
        if str(item or "").strip()
    }


def _normalize(text: Any) -> str:
    """归一化 summary：去空白、去方括号、小写。"""
    return str(text or "").strip().strip("[]【】").strip().lower()


def _cq_escape(text: Any) -> str:
    """CQ 码参数净化：逗号、方括号、& 都会破坏 CQ 解析。"""
    return (
        str(text or "")
        .replace("&", "")
        .replace(",", " ")
        .replace("，", " ")
        .replace("[", "")
        .replace("]", "")
        .replace("\u200b", "")
        .strip()
    )


def build_mface_cq(
    emoji_id: str,
    package_id: str,
    key: str,
    summary: str = "",
) -> str:
    """构造 mface CQ 码；summary 可选，用于客户端占位展示。"""
    parts = [
        "CQ:mface",
        f"emoji_id={emoji_id}",
        f"emoji_package_id={package_id}",
        f"key={key}",
    ]
    clean_summary = _cq_escape(summary)
    if clean_summary:
        parts.append(f"summary={clean_summary}")
    return "[" + ",".join(parts) + "]"


def extract_emoji_items(payload: Any) -> list[dict[str, Any]]:
    """从 fetch_custom_face_detail 的响应里取出表情条目列表。

    NapCat 的返回形态在不同版本间有差异：可能是 ``data.emojiInfoList``，
    也可能直接是 ``data`` 列表，两种都兼容。
    """
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        for key in ("emojiInfoList", "emoji_info_list", "list", "items"):
            items = data.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def match_emoji_item(
    items: list[dict[str, Any]],
    summary: str,
) -> dict[str, Any] | None:
    """按 summary 匹配收藏表情：先精确，再包含（双向）。"""
    target = _normalize(summary)
    if not target:
        return None

    for item in items:
        desc = _normalize(item.get("desc") or item.get("summary") or item.get("name"))
        if desc and desc == target:
            return item

    for item in items:
        desc = _normalize(item.get("desc") or item.get("summary") or item.get("name"))
        if desc and (target in desc or desc in target):
            return item
    return None


def parse_face_entry(
    entry: dict[str, Any],
    summary: str = "",
) -> str | None:
    """把一条收藏表情记录转成 mface CQ 码；字段不全返回 None。"""
    emoji_id = str(entry.get("md5") or entry.get("emoji_id") or "").strip()
    package_id = str(
        entry.get("epId") or entry.get("emoji_package_id") or ""
    ).strip()
    res_id = str(entry.get("resId") or entry.get("key") or "").strip()
    if not (emoji_id and package_id and res_id):
        logger.warning("收藏表情字段不完整: %s", entry)
        return None
    return build_mface_cq(emoji_id, package_id, res_id, summary)


async def resolve_custom_face(
    name: str,
    *,
    role_id: str,
    account_key: str,
    call_action: CallAction,
) -> str | None:
    """把配置里的表情名解析成 mface CQ 码。

    Args:
        name: 配置里的表情名（如 ``wow``）
        role_id: 当前说话的角色（用于权限检查）
        account_key: 账号标识（通常 napcat_ws_url），用于缓存隔离
        call_action: NapCat action 调用器，签名 ``(action, params, timeout)``

    Returns:
        mface CQ 码；未登记 / 角色无权限 / 收藏库里没有 / 字段不全时返回 None。
    """
    key = str(name or "").strip().lower()
    if not key:
        return None

    entry = load_face_config().get(key)
    if not entry:
        logger.info("收藏表情 %s 未在 qq_custom_faces.yaml 登记，跳过", key)
        return None

    roles = _allowed_roles(entry)
    normalized_role = str(role_id or "").strip().lower()
    if roles and normalized_role not in roles:
        logger.info(
            "角色 %s 无权发送收藏表情 %s（允许: %s），跳过",
            normalized_role,
            key,
            sorted(roles),
        )
        return None

    cache_key = (str(account_key or ""), key)
    cached = _face_cache.get(cache_key)
    if cached:
        return cached
    if cache_key in _face_cache:
        # 空串表示"暂时不可用"（未收藏 / 字段不全），冷却结束前不再重试
        if time.monotonic() < _failure_until.get(cache_key, 0.0):
            return None
        _face_cache.pop(cache_key, None)
        _failure_until.pop(cache_key, None)

    summary = str(entry.get("summary") or entry.get("label") or name).strip()
    code, payload = await call_action(
        "fetch_custom_face_detail", {"count": _FETCH_COUNT}, 8.0
    )
    if code != 0 or (isinstance(payload, dict) and payload.get("error")):
        logger.warning("拉取收藏表情失败（%s）: %s", key, payload)
        _remember_failure(cache_key)
        return None

    items = extract_emoji_items(payload)
    item = match_emoji_item(items, summary)
    if item is None:
        logger.warning(
            "收藏表情库里没有 summary≈%s 的表情（共 %d 条）；"
            "请先在 QQ 里收藏该表情，或调整 qq_custom_faces.yaml 的 summary",
            summary,
            len(items),
        )
        _remember_failure(cache_key)
        return None

    cq = parse_face_entry(item, summary)
    if not cq:
        _remember_failure(cache_key)
        return None
    _face_cache[cache_key] = cq
    logger.info("收藏表情 %s 已解析: %s", key, cq[:100])
    return cq


def clear_face_cache() -> None:
    """清空配置与解析缓存（测试用）。"""
    _config_cache.update({"ts": 0.0, "faces": {}})
    _face_cache.clear()
    _failure_until.clear()


__all__ = [
    "build_mface_cq",
    "clear_face_cache",
    "extract_emoji_items",
    "load_face_config",
    "match_emoji_item",
    "parse_face_entry",
    "resolve_custom_face",
]
