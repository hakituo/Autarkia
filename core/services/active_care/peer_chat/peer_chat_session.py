"""Peer Chat 会话记录（本地通道的落地点）。

一次互聊 = 一个 session：参与者、发起者、话题、逐条台词、摘要、起止时间。

为什么单独存一份，而不只依赖 ``peer_{role_id}`` 会话历史：
1. 老链路只有 QQ 真正投递成功才写历史；只用安卓端时没有 QQ 连接，互聊会
   整轮丢失，角色下一次完全不知道自己聊过什么。
2. 主对话需要「最近和谁聊过什么」的**结构化**摘要，而不是翻一段拼接文本。
3. 多人组队后，一条台词属于哪个组、和谁聊的，无法从单个 peer conversation 还原。

存储位置：``companion_data/dual_role/peer_chat_sessions.jsonl``（追加写，按时间倒序读取）。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.utils.logger import get_module_logger

logger = get_module_logger("PEER_CHAT", "peer_chat.log")

_MAX_SESSIONS_KEEP = 500


@dataclass
class PeerChatSession:
    """一次互聊的完整记录。"""

    script_id: str = ""
    participants: List[str] = field(default_factory=list)
    initiator: str = ""
    topic: str = ""
    lines: List[Dict[str, str]] = field(default_factory=list)
    summary: str = ""
    mentioned_user: bool = False
    started_at: float = 0.0
    ended_at: float = 0.0
    # local / qq / both，记录这次实际走了哪些通道
    channels: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PeerChatSession":
        if not isinstance(data, dict):
            return cls()
        return cls(
            script_id=str(data.get("script_id") or ""),
            participants=[
                str(p).strip().lower()
                for p in (data.get("participants") or [])
                if str(p).strip()
            ],
            initiator=str(data.get("initiator") or "").strip().lower(),
            topic=str(data.get("topic") or ""),
            lines=[
                {
                    "role": str(line.get("role") or "").strip().lower(),
                    "content": str(line.get("content") or ""),
                }
                for line in (data.get("lines") or [])
                if isinstance(line, dict) and str(line.get("content") or "").strip()
            ],
            summary=str(data.get("summary") or ""),
            mentioned_user=bool(data.get("mentioned_user")),
            started_at=float(data.get("started_at") or 0.0),
            ended_at=float(data.get("ended_at") or 0.0),
            channels=[str(c) for c in (data.get("channels") or []) if str(c).strip()],
        )


def build_session_summary(
    lines: Iterable[Dict[str, Any]],
    participants: Iterable[str],
    topic: str = "",
    *,
    max_chars: int = 90,
) -> str:
    """用规则拼一句摘要（不额外调 LLM）。

    取双方各一句有信息量的话，避免把「嗯」「好」这种应答当成摘要主体。
    """
    from core.services.dual_role.personas import get_role_names

    names = {
        str(p).strip().lower(): get_role_names(str(p).strip().lower())["cn_name"]
        for p in participants
        if str(p).strip()
    }
    picked: List[str] = []
    seen_roles: set = set()
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        role = str(line.get("role") or "").strip().lower()
        content = str(line.get("content") or "").strip()
        if not role or not content or role in seen_roles:
            continue
        if len(content) < 4:
            continue
        seen_roles.add(role)
        picked.append(f"{names.get(role, role)}：{content}")
        if len(picked) >= 2:
            break

    head = f"聊了{topic}，" if topic else ""
    body = "；".join(picked)
    text = f"{head}{body}" if head else body
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


class PeerChatSessionStore:
    """JSONL 会话存储（进程内单例）。"""

    def __init__(self, path: Optional[Path] = None):
        self._path = path

    @property
    def path(self) -> Path:
        if self._path is not None:
            return self._path
        from core.utils.data_paths import get_dual_role_data_dir

        return Path(get_dual_role_data_dir()) / "peer_chat_sessions.jsonl"

    def append(self, session: PeerChatSession) -> None:
        if not session.script_id:
            session.script_id = uuid.uuid4().hex[:12]
        if not session.started_at:
            session.started_at = time.time()
        if not session.ended_at:
            session.ended_at = session.started_at
        try:
            path = self.path
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(session.to_dict(), ensure_ascii=False) + "\n")
            self._trim_if_needed(path)
        except Exception as exc:
            logger.warning("PeerChat 会话落盘失败: %s", exc)

    def _trim_if_needed(self, path: Path) -> None:
        """超过上限时保留最近 N 条（重写整个文件，量小可接受）。"""
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) <= _MAX_SESSIONS_KEEP:
                return
            path.write_text(
                "\n".join(lines[-_MAX_SESSIONS_KEEP:]) + "\n",
                encoding="utf-8",
            )
        except Exception:
            pass

    def load_recent(self, limit: int = 50) -> List[PeerChatSession]:
        try:
            path = self.path
            if not path.is_file():
                return []
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        sessions: List[PeerChatSession] = []
        for raw in lines[-max(1, limit) :]:
            try:
                sessions.append(PeerChatSession.from_dict(json.loads(raw)))
            except Exception:
                continue
        return sessions

    def get_recent_for_role(
        self,
        role_id: str,
        *,
        limit: int = 3,
        within_seconds: float = 86400.0,
    ) -> List[PeerChatSession]:
        """取该角色参与过的最近会话（默认 24 小时内）。"""
        rid = str(role_id or "").strip().lower()
        if not rid:
            return []
        cutoff = time.time() - max(0.0, float(within_seconds))
        matched: List[PeerChatSession] = []
        for session in reversed(self.load_recent(limit=_MAX_SESSIONS_KEEP)):
            if session.ended_at and session.ended_at < cutoff:
                continue
            if rid in session.participants:
                matched.append(session)
            if len(matched) >= limit:
                break
        return matched


_store: Optional[PeerChatSessionStore] = None


def get_peer_chat_session_store() -> PeerChatSessionStore:
    global _store
    if _store is None:
        _store = PeerChatSessionStore()
    return _store


def build_recent_peer_chat_context(
    role_id: str,
    *,
    limit: int = 2,
    within_seconds: float = 86400.0,
) -> str:
    """主对话用：当前角色视角的「最近和其他角色聊过什么」。

    只返回包含该角色的会话，且不注入其他人的私有信息——剧本本身已通过
    知识防火墙校验，这里只做结构化摘要。
    """
    from core.services.dual_role.personas import get_role_names

    sessions = get_peer_chat_session_store().get_recent_for_role(
        role_id, limit=limit, within_seconds=within_seconds
    )
    if not sessions:
        return ""

    lines: List[str] = ["【最近和其他角色聊过的事】"]
    for session in sessions:
        others = [
            get_role_names(p)["cn_name"]
            for p in session.participants
            if p != str(role_id).strip().lower()
        ]
        who = "、".join(others) or "别人"
        summary = session.summary or "（没有留下摘要）"
        lines.append(f"- 和{who}：{summary}")
    lines.append("这些是你自己的经历，不需要主动汇报；只有在话题自然相关时才可以提起。")
    return "\n".join(lines)
