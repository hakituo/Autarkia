"""Peer Chat 投递通道。

一次互聊生成完剧本后，按可用通道分发（可同时生效）：

- ``local``：写会话记录 + 社交事件 + 记忆。**永远可用**，不依赖 QQ 或客户端在线。
  这是「只用安卓端、不挂 QQ」时互聊仍然有意义的根本保证。
- ``qq``：把每条台词投递到其他参与者的 QQ（沿用旧行为）。只有对应角色
  真的有在线 QQ 连接时才执行；没有连接就跳过，不算失败。

两者都不要求用户在线：用户不看互聊内容，互聊的价值在角色自己的连续记忆。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core.utils.logger import get_module_logger

logger = get_module_logger("PEER_CHAT", "peer_chat.log")


@dataclass
class PeerChatDeliveryResult:
    delivered: bool = False
    channels: List[str] = field(default_factory=list)
    should_notify_user: bool = False
    notify_content: str = ""


def participants_to_names(participants: Iterable[str]) -> Dict[str, str]:
    from core.services.dual_role.personas import get_role_names

    return {
        str(p).strip().lower(): get_role_names(str(p).strip().lower())["cn_name"]
        for p in participants
        if str(p).strip()
    }


# ============================================================
# 本地通道
# ============================================================

async def deliver_local(
    *,
    session,
    host: Any = None,
    write_peer_conversation: bool = True,
) -> bool:
    """写会话记录 + 社交事件 +（可选）peer conversation。

    不抛异常：本地通道失败也不能连累 QQ 投递，反之亦然。
    """
    ok = False

    try:
        from core.services.active_care.peer_chat.peer_chat_session import (
            get_peer_chat_session_store,
        )

        get_peer_chat_session_store().append(session)
        ok = True
    except Exception as exc:
        logger.warning("PeerChat 本地会话记录失败: %s", exc)

    # 社交事件：让后续主动关怀/关系上下文知道「她们聊过这个」。
    # 一次互聊只记一条，detail 里带全部参与者，避免每人都记一遍造成重复。
    try:
        from core.services.dual_role.social_events import get_social_event_engine

        engine = get_social_event_engine()
        if engine is not None:
            names = participants_to_names(session.participants)
            who = "、".join(names.get(p, p) for p in session.participants)
            body = session.summary or f"聊了{len(session.lines)}轮"
            engine.record_shared_life_event(
                event_type="peer_chat",
                detail=f"{who}：{body}",
                source="peer_chat",
                learned_by=session.initiator or (session.participants or ["aveline"])[0],
            )
    except Exception as exc:
        logger.debug("PeerChat 社交事件写入失败: %s", exc)

    # 保留旧行为：逐条落到 peer_{role_id} 会话，供旧读取路径继续可用。
    if write_peer_conversation and host is not None:
        try:
            from core.core_engine.service_singletons import get_aveline_service

            service = get_aveline_service()
            if service is not None:
                names = participants_to_names(session.participants)
                conv_ids = [f"peer_{p}" for p in session.participants]
                for line in session.lines:
                    speaker = str(line.get("role") or "").strip().lower()
                    content = str(line.get("content") or "").strip()
                    if not content:
                        continue
                    text = f"{names.get(speaker, speaker)}: {content}"
                    for conv_id in conv_ids:
                        try:
                            await service.append_proactive_message(
                                conversation_id=conv_id,
                                content=text,
                                thought="peer_chat剧本记录",
                            )
                        except Exception:
                            continue
        except Exception as exc:
            logger.debug("PeerChat 写 peer conversation 失败: %s", exc)

    return ok


# ============================================================
# QQ 通道
# ============================================================

def _online_connections_by_role(connections: Sequence[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    result: Dict[str, Dict[str, str]] = {}
    for conn in connections or []:
        role_id = str(conn.get("role_id", "")).strip().lower()
        if role_id:
            result[role_id] = conn
    return result


async def deliver_qq(
    *,
    session,
    cfg_by_role: Dict[str, Dict[str, str]],
    master_qq_id: str,
    online_connections: Sequence[Dict[str, str]] = (),
) -> bool:
    """把每条台词投递到「除说话者外」的其他参与者 QQ。

    Args:
        session: PeerChatSession
        cfg_by_role: role_id -> {role_name, profile_filename, qq_id}
        master_qq_id: 主人 QQ（构建 conversation_id 用）
        online_connections: 当前在线的多 QQ 连接；只投递给在线角色

    Returns:
        是否至少投递成功一条
    """
    if not master_qq_id:
        return False

    from clients.bots.qq.peer_chat import PeerChatManager
    from clients.bots.qq.utils import build_persona_conversation_id
    from core.core_engine.service_singletons import get_aveline_service

    service = get_aveline_service()
    if service is None:
        logger.warning("PeerChat QQ 通道: AvelineService 不可用")
        return False

    online = _online_connections_by_role(online_connections)
    if not online:
        return False

    base_cid = f"private_{master_qq_id}"
    names = participants_to_names(session.participants)
    delivered_any = False

    for index, line in enumerate(session.lines):
        speaker = str(line.get("role") or "").strip().lower()
        content = str(line.get("content") or "").strip()
        if not speaker or not content:
            continue

        targets = [
            role_id
            for role_id in session.participants
            if role_id != speaker and role_id in online
        ]
        for target_role in targets:
            target_cfg = cfg_by_role.get(target_role) or {}
            persona_fn = str(target_cfg.get("profile_filename") or "").strip()
            target_qq = str(target_cfg.get("qq_id") or "").strip()
            if not persona_fn or not target_qq:
                continue
            target_cid = build_persona_conversation_id(base_cid, persona_fn)
            extra = {
                "target_qq_id": target_qq,
                "is_peer_script": True,
                "message_type": "peer_script",
                "peer_speaker": names.get(speaker, speaker),
                "role_id": speaker,
                "peer_participants": list(session.participants),
                "peer_script_id": session.script_id,
            }
            try:
                result = await service.dispatch_proactive_message(
                    target_conversation_id=target_cid,
                    content=content,
                    thought="多角色互聊剧本",
                    message_type="text",
                    client_type="qq",
                    original_primary_conversation_id=base_cid,
                    extra_payload=extra,
                )
                if result.get("delivered"):
                    delivered_any = True
            except Exception as exc:
                logger.warning(
                    "PeerChat QQ 投递失败 speaker=%s target=%s: %s",
                    speaker, target_role, exc,
                )

        # 消息间延迟（最后一条不需要）
        if index < len(session.lines) - 1:
            try:
                delay = PeerChatManager.calc_message_delay(content)
                await asyncio.sleep(delay)
            except Exception:
                pass

    return delivered_any


# ============================================================
# 统一入口
# ============================================================

async def deliver_peer_chat(
    *,
    session,
    host: Any = None,
    qq_cfg_by_role: Optional[Dict[str, Dict[str, str]]] = None,
    master_qq_id: str = "",
    online_connections: Sequence[Dict[str, str]] = (),
    local_enabled: bool = True,
    qq_enabled: bool = True,
    should_notify_user: bool = False,
    notify_content: str = "",
) -> PeerChatDeliveryResult:
    """按通道分发，任一通道成功即视为本次互聊成立。"""
    result = PeerChatDeliveryResult(
        should_notify_user=should_notify_user,
        notify_content=notify_content,
    )

    if local_enabled:
        try:
            if await deliver_local(session=session, host=host):
                result.channels.append("local")
                result.delivered = True
        except Exception as exc:
            logger.warning("PeerChat 本地通道异常: %s", exc)

    if qq_enabled:
        try:
            if await deliver_qq(
                session=session,
                cfg_by_role=qq_cfg_by_role or {},
                master_qq_id=master_qq_id,
                online_connections=online_connections,
            ):
                result.channels.append("qq")
                result.delivered = True
        except Exception as exc:
            logger.warning("PeerChat QQ 通道异常: %s", exc)

    return result
