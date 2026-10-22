from abc import ABC, abstractmethod
from typing import Any, Dict, Type, Optional
from pydantic import BaseModel


class BaseTool(ABC):
    """
    Base class for all tools.
    """

    name: str
    description: str
    args_schema: Optional[Type[BaseModel]] = None
    # Short hint for prompt injection (overrides description if set)
    short_description: Optional[str] = None
    # Category for grouping (e.g. "memory", "daily", "study", "utility")
    category: str = "utility"
    # Whether this tool is enabled by default
    enabled_by_default: bool = True

    def set_runtime_context(self, context: Dict[str, Any]) -> None:
        """Inject runtime context (agent, user_id, etc.) before execution."""
        self._runtime_context = context

    def _get_ctx(self, key: str, default: Any = None) -> Any:
        """Convenience accessor for runtime context keys."""
        return getattr(self, "_runtime_context", {}).get(key, default)

    def _is_master(self) -> bool:
        """判断当前会话是否属于 Master。

        唯一实现：原先 device/base.py、device/set_app_limit.py、
        screen_capture_tool.py 各抄了一份逐字相同的副本，已收拢到这里。

        判断规则：
        1. conversation_id 为 default / default_user → Master（本地默认会话）
        2. conversation_id 的 session 段（__ 之前）为 private_{MASTER_QQ_ID} → Master
        3. 其他情况 → 非 Master
        """
        cid = str(self._get_ctx("user_id") or "").strip().lower()
        if not cid:
            return False
        if cid in {"default", "default_user"}:
            return True
        # 取 session_id 段（__ 之前），如 private_12345__persona__aveline → private_12345
        session_part = cid.split("__")[0]
        try:
            from clients.bots.qq.settings import MASTER_QQ_ID

            master_id = str(MASTER_QQ_ID or "").strip()
            if master_id and session_part == f"private_{master_id}":
                return True
        except Exception:
            # 非 QQ 部署环境，回退：default 系列已判断，其余视为非 Master
            pass
        return False

    @abstractmethod
    async def _run(self, *args, **kwargs) -> Any:
        """
        Implementation of the tool.
        """
        pass

    async def run(self, *args, **kwargs) -> str:
        """
        Execute the tool and return the result as a string.
        """
        try:
            result = await self._run(*args, **kwargs)
            return str(result)
        except Exception as e:
            return f"Error executing tool {self.name}: {str(e)}"

    def current_role_scope(self) -> str:
        """当前会话所属角色的 scope（aveline / ling / ye ...）。

        工具里凡是「按当前角色取数据 / 判断角色」的地方都应该用它，不要直接读
        全局 persona 单例——HTTP 聊天路径从不更新那个单例，多角色并发时会取到
        别的角色，导致跨角色读写（表现为角色串味）。
        """
        return resolve_tool_role_scope(self)


def resolve_tool_role_scope(tool: BaseTool) -> str:
    """判定工具当前所属角色的 scope。

    优先用运行时上下文注入的 ``profile_filename``，其次 ``user_id``
    （conversation_id）——它们由每次请求单独注入，多角色并发安全。
    都没有时才回退全局 persona 单例；该单例在 HTTP 聊天路径下不可靠，
    因此只能作为最后的尽力而为。
    """
    try:
        from core.utils.data.scope_registry import (
            get_registered_role_scopes,
            resolve_data_scope_from_conversation_id,
            resolve_persona_slug_scope,
        )

        valid = get_registered_role_scopes()
        filename = str(tool._get_ctx("profile_filename") or "").strip()  # noqa: SLF001
        if filename:
            resolved = resolve_persona_slug_scope(filename)
            if resolved in valid:
                return resolved

        cid = str(tool._get_ctx("user_id") or "").strip()  # noqa: SLF001
        if cid:
            resolved = resolve_data_scope_from_conversation_id(cid)
            if resolved in valid:
                return resolved
    except Exception:
        pass
    try:
        from core.utils.data_paths import _resolve_scope_from_active_persona

        return _resolve_scope_from_active_persona()
    except Exception:
        pass
    return "aveline"
