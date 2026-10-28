"""主对话每轮自动注入梗概（门面）：读开关、算 SFW 口径、放工作线程并限时。

设计见 ``.trae/specs/notes_injection_spec.md``。开关 ``memory.notes_injection_enabled``
默认关；关时调用方不做任何读盘 / 检索，prompt 与旧版逐字节一致。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from core.utils.logger import get_logger

from .runner import build_block, reset_injection_cache

logger = get_logger("NotesInjection")

#: 单轮取数限时（秒）；超时本轮不注入，工作线程跑完会填缓存
TIMEOUT_SECONDS = 1.5


def injection_enabled() -> bool:
    try:
        from config.integrated_config import get_settings

        return bool(getattr(get_settings().memory, "notes_injection_enabled", False))
    except Exception:  # noqa: BLE001 - 读不到配置按默认关闭
        return False


def private_local_only() -> bool:
    """隐私梗概只进本地模型（开关 ``memory.notes_injection_private_local_only``，默认开）。"""
    try:
        from config.integrated_config import get_settings

        return bool(getattr(get_settings().memory, "notes_injection_private_local_only", True))
    except Exception:  # noqa: BLE001 - 读不到配置按更保守的「开」
        return True


def exclude_sensitive_for(*, is_cloud: bool, is_sensitive_mode: bool) -> bool:
    """是否剔除隐私梗概：云端且开了「只进本地」时一律剔除；否则与 history_fetch 同口径
    （全局隐私隔离开、且当前不在隐私模式就剔除）。"""
    if is_cloud and private_local_only():
        return True
    from core.utils.privacy import should_exclude_sensitive

    return should_exclude_sensitive(is_sensitive_mode=is_sensitive_mode)


async def build_notes_injection(
    *,
    user_id: str,
    message_text: str,
    is_cloud: bool,
    is_sensitive_mode: bool,
    existing: Sequence[str] = (),
    timeout: float = TIMEOUT_SECONDS,
) -> str:
    """返回本轮梗概注入块；没有可注入内容、超时或出错时返回空串。"""
    if not user_id:
        return ""
    try:
        exclude = exclude_sensitive_for(is_cloud=is_cloud, is_sensitive_mode=is_sensitive_mode)
        return await asyncio.wait_for(
            asyncio.to_thread(
                build_block,
                user_id=user_id,
                query=message_text,
                exclude_sensitive=exclude,
                existing=list(existing),
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.info("梗概注入超时（>%.1fs），本轮跳过", timeout)
    except Exception as exc:  # noqa: BLE001 - 注入失败不得影响主对话
        logger.warning("梗概注入失败，本轮跳过: %s: %s", type(exc).__name__, exc)
    return ""


__all__ = [
    "TIMEOUT_SECONDS",
    "build_block",
    "build_notes_injection",
    "exclude_sensitive_for",
    "injection_enabled",
    "private_local_only",
    "reset_injection_cache",
]
