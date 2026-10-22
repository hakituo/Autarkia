"""朋友印象记录工具：把角色新想到、人设里还没有的朋友写成一张人物卡。

落位固定为当前角色 scope 下的 ``knowledge/people/<slug>.json``。角色资料的
装配链路（``persona_system.prompt.layered_context`` → ``context_engine.load_chunks``）
会对 ``knowledge`` 目录做递归 ``rglob("*.json")`` 发现，因此这里写出的卡会自动
进入检索目录；下一轮用户提到该名字时，靠 ``retrieval.keywords`` 词面匹配被检回。
不写 ``legacy/``，也不新建顶层角色目录。

安全约定：
- 只写当前角色自己的 ``knowledge/people/``，并用 ``is_relative_to`` 做越界校验。
- 命中已有卡（含作者写好的详细资料）时**只写工具自有的 ``facts.impression``**，
  绝不覆盖 ``facts.relationship`` 等既有内容。
- 全部 I/O 走 ``async_safe_json_*``，时间只经 ``core.utils.time_utils``。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from core.tools.base import BaseTool
from core.utils.async_locks import LazyAsyncLock
from core.utils.atomic_io import async_safe_json_dump, async_safe_json_load
from core.utils.common import get_project_root
from core.utils.data.scope_registry import get_registered_role_scopes
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

logger = get_logger("FriendImpressionTool")

_CONFIGS_ROOT = Path(get_project_root()) / "core" / "character" / "configs"
_WRITE_LOCK = LazyAsyncLock()
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TOOL_PROVENANCE_KIND = "tool_recorded_friend_impression"


def _sanitize_slug(name: str) -> str:
    """把朋友名归一成一个安全的文件名片段；中文名保留原字符。"""
    text = _INVALID_FILENAME_CHARS.sub("", str(name or "").strip())
    text = re.sub(r"\s+", "_", text)
    return text.strip("._")


def _resolve_people_dir(scope: str) -> Optional[Path]:
    """解析当前角色的 knowledge/people 目录，越界或未注册返回 None。"""
    normalized = str(scope or "").strip().lower()
    if not normalized or normalized not in get_registered_role_scopes():
        return None
    base = (_CONFIGS_ROOT / normalized).resolve()
    target = (base / "knowledge" / "people").resolve()
    try:
        if not target.is_relative_to(base):
            return None
    except AttributeError:  # pragma: no cover - Python < 3.9 compatibility
        if not str(target).startswith(str(base)):
            return None
    return target


def _merge_unique(primary: object, extra: object) -> list[str]:
    """保序合并两组字符串，按去空白后的小写去重。"""
    result: list[str] = []
    seen: set[str] = set()

    def _iter(value: object):
        if isinstance(value, (list, tuple, set)):
            yield from value
        elif value is not None:
            yield value

    for raw in (*_iter(primary), *_iter(extra)):
        text = str(raw or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _find_existing_card(people_dir: Path, names: list[str]) -> Optional[Path]:
    """按 facts.identity 的名字/别名精确匹配已有卡，避免同一人重复建卡。"""
    wanted = {str(item or "").strip().lower() for item in names if str(item or "").strip()}
    if not wanted:
        return None
    for path in sorted(people_dir.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(document, dict):
            continue
        facts = document.get("facts")
        identity = facts.get("identity") if isinstance(facts, dict) else None
        if not isinstance(identity, dict):
            continue
        candidates = [identity.get("name"), *(identity.get("aliases") or [])]
        if any(str(item or "").strip().lower() in wanted for item in candidates):
            return path
    return None


class RecordFriendImpressionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(
        min_length=1,
        max_length=40,
        description="这位朋友的名字，或你平时称呼她的方式",
    )
    impression: str = Field(
        min_length=1,
        max_length=600,
        description="你对这位朋友的印象：她是谁、你们怎么认识、她给你什么感觉",
    )
    aliases: Optional[list[str]] = Field(
        default=None,
        description="你还会怎么称呼她，便于以后想起来；没有就不填",
    )


class RecordFriendImpressionTool(BaseTool):
    name = "record_friend_impression"
    description = (
        "当你想到、遇到或聊起一个你还不熟悉、人设里也没有记录的朋友时，用这个工具把"
        "你对她的印象写下来，以后就能想起她是谁。只写你自己的印象和了解，不写关于主人"
        "的隐私，也不要凭空编造没发生过的事。同一个人重复记录会更新已有卡片，但不会覆盖"
        "已经写好的详细资料。记录完成后不要在对用户的回复里提到工具本身。"
    )
    short_description = "记下一个还没记录过的朋友的印象"
    category = "memory"
    args_schema = RecordFriendImpressionInput

    async def _run(self, **kwargs) -> str:
        # 首次 await 前快照上下文，防止共享工具实例被并发请求覆盖。
        context = dict(getattr(self, "_runtime_context", {}))
        allowed = context.get("allowed_tool_names")
        if allowed is not None and self.name not in allowed:
            return json.dumps({"ok": False, "error": "当前会话无权调用此工具"}, ensure_ascii=False)
        request = RecordFriendImpressionInput.model_validate(kwargs)
        result = await record_friend_impression(
            scope=self.current_role_scope(),
            name=request.name,
            impression=request.impression,
            aliases=request.aliases or [],
        )
        return json.dumps(result, ensure_ascii=False)


async def record_friend_impression(
    *,
    scope: str,
    name: str,
    impression: str,
    aliases: list[str],
) -> dict:
    """写入或更新当前角色的一张朋友印象卡。"""
    people_dir = _resolve_people_dir(scope)
    if people_dir is None:
        return {"ok": False, "error": f"当前角色（{scope}）没有可写入的朋友目录"}

    names = _merge_unique([name], aliases)
    async with _WRITE_LOCK:
        people_dir.mkdir(parents=True, exist_ok=True)
        now = get_current_time()
        date_text = now.strftime("%Y-%m-%d")
        existing = _find_existing_card(people_dir, names)

        if existing is not None:
            path = existing
            card = await async_safe_json_load(path, default={})
            if not isinstance(card, dict):
                card = {}
            facts = card.get("facts")
            if not isinstance(facts, dict):
                facts = {}
                card["facts"] = facts
            identity = facts.get("identity")
            if not isinstance(identity, dict):
                identity = {}
                facts["identity"] = identity
            identity.setdefault("name", name)
            merged_aliases = _merge_unique(identity.get("aliases"), aliases)
            if merged_aliases:
                identity["aliases"] = merged_aliases
            # 只写工具自有字段，不动作者写好的 relationship 等正文。
            facts["impression"] = impression
            retrieval = card.get("retrieval")
            if not isinstance(retrieval, dict):
                retrieval = {}
                card["retrieval"] = retrieval
            retrieval["keywords"] = _merge_unique(retrieval.get("keywords"), names)
            card["revision"] = date_text
            provenance = card.get("provenance")
            if isinstance(provenance, dict):
                provenance["last_recorded_at"] = now.isoformat()
            created = False
        else:
            slug = _sanitize_slug(name) or hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
            path = people_dir / f"{slug}.json"
            if path.exists():
                digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
                path = people_dir / f"{slug}_{digest}.json"
            identity: dict = {"name": name}
            if aliases:
                identity["aliases"] = list(aliases)
            card = {
                "id": f"{scope}.person.{path.stem}",
                "topic": f"person_{path.stem}",
                "projection": {"mode": "retrieval"},
                "retrieval": {"keywords": names},
                "facts": {
                    "identity": identity,
                    # 与角色关系基线（relationship.seeding）对齐，让它也能进 SOCIAL 基线。
                    "relationship": impression,
                    "impression": impression,
                },
                "availability": {"interaction_modes": ["ordinary", "private"]},
                "provenance": {
                    "kind": _TOOL_PROVENANCE_KIND,
                    "recorded_at": now.isoformat(),
                    "recorded_by": scope,
                },
                "revision": date_text,
            }
            created = True

        resolved = path.resolve()
        if not resolved.is_relative_to(people_dir.resolve()):
            return {"ok": False, "error": "目标路径越界"}
        try:
            await async_safe_json_dump(card, path)
        except OSError as exc:
            logger.error("朋友印象卡写入失败: %s (%s)", path, exc)
            return {"ok": False, "error": f"朋友卡片写入失败：{exc}"}

    _clear_knowledge_cache(people_dir)
    return {"ok": True, "created": created, "path": str(path.relative_to(_CONFIGS_ROOT)), "name": name}


def _clear_knowledge_cache(people_dir: Path) -> None:
    """尽力清一次 knowledge 目录缓存，让新卡下一轮立即可被检回。"""
    try:
        from core.agents.chat_agent_components.persona_system.prompt.context_engine import (
            clear_knowledge_cache,
        )

        clear_knowledge_cache(people_dir.parent.resolve())
    except Exception as exc:  # noqa: BLE001 - 缓存清理失败不影响写入结果
        logger.debug("knowledge 缓存清理失败（忽略）: %s", exc)
