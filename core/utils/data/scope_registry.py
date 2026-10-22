"""角色数据 scope 的唯一注册表与解析入口。

持久化目录一律由 ``core/character/configs/`` 下人设声明的 ``meta.scope`` 决定。
Persona 1.0 的单文件与 Persona 2.0 的角色目录统一扫描，分层角色用
``<scope>/core_<scope>.json`` 声明身份和历史别名。

文件名、显示名、历史别名只用于找到这个稳定 scope，不能直接成为新的数据目录名。
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path
from typing import Optional

import structlog

from config.debug_config import is_debug_enabled
from core.utils.common import get_project_root

logger = structlog.get_logger(__name__)

_BUILTIN_ROLE_SCOPES = {"aveline", "ling", "xiaolu", "yeye"}
_SPECIAL_SCOPES = {"user", "dual_role"}
_SCOPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

# 保留这些可变对象供旧导入路径兼容；刷新时原地更新，避免引用失效。
_VALID_SCOPES: set[str] = set(_BUILTIN_ROLE_SCOPES | _SPECIAL_SCOPES)
_DYNAMIC_SCOPES: dict[str, dict] = {}
_PERSONA_SLUG_TO_SCOPE: dict[str, str] = {}
# scope → 规范 persona 入口文件名。正向索引只回答「这个别名属于谁」，回答不了
# 「这个 scope 是哪个角色」；主动关怀分发在单角色模式下只有 scope、拿不到
# profile_filename，需要靠这张反向表补齐 payload 的归属信息。
_SCOPE_TO_PROFILE_FILENAME: dict[str, str] = {}
# 「无法反解角色」时生成的隔离 scope（persona_<hash>），与真实角色 scope 区分开
_ISOLATED_SCOPES: set[str] = set()

_BUILTIN_SLUG_TO_SCOPE = {
    "aveline": "aveline",
    "core_aveline": "aveline",
    "ling": "ling",
    "core_ling": "ling",
    "ling": "ling",
    "xiaolu": "xiaolu",
    "qq_official_1": "xiaolu",
    "yeye": "yeye",
    "qq_official_2": "yeye",
    # QQ 端人设 slug：qq/ 目录下已不再放 aveline / ling 的人设文件，
    # 但历史会话 ID 仍在用这些 slug（如 private_xxx__persona__aveline_qq_master）。
    # 不登记会解析不出角色，导致 QQ 的记忆进不了对应角色、也没法跨平台合并。
    "aveline_qq": "aveline",
    "aveline_qq_master": "aveline",
    "aveline_qq_group": "aveline",
    "ling_qq": "ling",
    "ling_qq_love": "ling",
    "ling_qq_group": "ling",
}

_PERSONA_CONFIGS_DIR = "core/character/configs"
_REGISTRY_INITIALIZED = False
_REGISTRY_LOCK = threading.RLock()
_ACTIVE_CONFIGS_DIR: Optional[Path] = None
_CONFIG_SNAPSHOT: tuple[int, int] = (0, 0)
_CONFIG_CHECK_INTERVAL_SECONDS = 2.0
_LAST_CONFIG_CHECK_MONOTONIC = 0.0


def _default_configs_dir() -> Path:
    return (get_project_root() / _PERSONA_CONFIGS_DIR).resolve()


def _normalize_slug(value: object) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    stem = text.rsplit("/", 1)[-1]
    if stem.lower().endswith(".json"):
        stem = stem[:-5]
    return stem.strip().lower()


def _slug_candidates(value: object) -> set[str]:
    raw = _normalize_slug(value)
    if not raw:
        return set()
    safe = re.sub(r"[^a-z0-9_\u4e00-\u9fff]+", "_", raw).strip("_")
    return {candidate for candidate in (raw, safe) if candidate}


# 客户端生成 conversation_id 时惯用的平台前缀；顺序很重要，长前缀必须排在前面。
# 安卓端 ``web_<persona>`` / ``web_role_<hash>`` 都带这些前缀，不剥离就匹配不到
# persona slug，会塌进默认角色目录，造成多个角色共用同一份记忆（角色串味）。
_CLIENT_CID_PREFIXES = (
    "web_role_",
    "circle_role_",
    "web_",
    "mobile_",
    "android_",
    "app_",
)

# 客户端 role 级兜底会话的形态：平台前缀 + role_ + 角色名哈希，例 ``web_role_3f2a1b9c``
_ROLE_DIGEST_CID_PATTERN = re.compile(r"^[a-z0-9_]*role_[0-9a-f]{6,}$")

# 不参与「同一角色全平台合并」的会话：群聊、双角色互聊、外部平台。
# 这些场景的对谈不属于主人与角色之间的私人记忆，混进来会造成串味。
_NON_MERGEABLE_CID_PREFIXES = (
    "group_",
    "peer_",
    "tg_",
    "telegram_",
    "telegram_group_",
    "telegram_private_",
)


def cid_slug_candidates(conversation_id: object) -> set[str]:
    """从客户端 conversation_id 提取 persona slug 候选集。

    在原始 slug 之外，额外补上「剥离平台前缀」后的候选，让
    ``web_core_ling.json`` 这类客户端会话 ID 也能命中 ``core_ling`` 的 scope。
    """
    candidates = set(_slug_candidates(conversation_id))
    raw = _normalize_slug(conversation_id)
    if not raw:
        return candidates
    for prefix in _CLIENT_CID_PREFIXES:
        if raw.startswith(prefix):
            stripped = raw[len(prefix) :].strip("_")
            if stripped:
                candidates |= _slug_candidates(stripped)
            break
    return candidates


def _config_snapshot(configs_dir: Path) -> tuple[int, int]:
    count = 0
    newest_mtime_ns = 0
    if not configs_dir.exists():
        return count, newest_mtime_ns
    for path in configs_dir.rglob("*.json"):
        try:
            stat = path.stat()
        except OSError:
            continue
        count += 1
        newest_mtime_ns = max(newest_mtime_ns, stat.st_mtime_ns)
    return count, newest_mtime_ns


def _infer_builtin_scope(json_file: Path, data: dict) -> str:
    """兼容旧内置 persona；新角色必须显式声明 meta.scope。"""
    identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    tokens = " ".join(
        [
            json_file.stem,
            str(identity.get("name") or ""),
            str(identity.get("cn_name") or ""),
        ]
    ).lower()
    if "ling" in tokens or "Ling" in tokens:
        return "ling"
    if "aveline" in tokens or "七濑" in tokens or "Aveline" in tokens:
        return "aveline"
    return ""


def _register_alias(alias: object, scope: str) -> None:
    for slug in _slug_candidates(alias):
        existing = _PERSONA_SLUG_TO_SCOPE.get(slug)
        if existing and existing != scope:
            logger.warning(
                "persona scope 别名冲突，保留先注册值",
                slug=slug,
                existing_scope=existing,
                ignored_scope=scope,
            )
            continue
        _PERSONA_SLUG_TO_SCOPE[slug] = scope


# 同一 scope 常有多个声明文件（aveline 既有 aveline/core_aveline.json，也有
# study/Aveline_Study.json；ling 既有 core_ling.json，也有 variants/ling_b.json）。
# 反查必须给出唯一且稳定的规范入口，否则客户端归属会随扫描顺序漂移。
# 优先级：顶层 ``core_<scope>.json`` > ``<scope>/core_<scope>.json`` > ``<scope>.json``。
def _entry_rank(scope: str, relative_name: str) -> tuple[int, int, str]:
    lowered = relative_name.lower()
    for index, expected in enumerate(
        (f"core_{scope}.json", f"{scope}/core_{scope}.json", f"{scope}.json")
    ):
        if lowered == expected:
            return (index, len(relative_name), lowered)
    return (3, len(relative_name), lowered)


def _register_persona_entry(
    scope: str,
    json_file: Path,
    configs_dir: Optional[Path],
) -> None:
    """登记 scope 的规范入口文件名，只保留优先级最高的那个。"""
    base = configs_dir or _ACTIVE_CONFIGS_DIR or _default_configs_dir()
    try:
        relative = json_file.resolve().relative_to(Path(base).resolve()).as_posix()
    except (OSError, ValueError):
        relative = json_file.name
    if not relative:
        return
    current = _SCOPE_TO_PROFILE_FILENAME.get(scope)
    if current is not None and _entry_rank(scope, current) <= _entry_rank(scope, relative):
        return
    _SCOPE_TO_PROFILE_FILENAME[scope] = relative


def _register_persona(
    json_file: Path,
    data: dict,
    configs_dir: Optional[Path] = None,
) -> None:
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    scope = str(meta.get("scope") or "").strip().lower()
    if not scope:
        scope = _infer_builtin_scope(json_file, data)
    if not scope:
        return
    if not _SCOPE_PATTERN.fullmatch(scope):
        logger.warning(
            "忽略非法 persona scope；必须使用英文 snake_case",
            path=str(json_file),
            scope=scope,
        )
        return

    _VALID_SCOPES.add(scope)
    _register_persona_entry(scope, json_file, configs_dir)
    if scope not in _BUILTIN_ROLE_SCOPES:
        info = _DYNAMIC_SCOPES.setdefault(
            scope,
            {"dir": f"{scope}_data", "slugs": set()},
        )
        info["slugs"].add(json_file.stem.lower())

    _register_alias(scope, scope)
    _register_alias(json_file.stem, scope)

    identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    for key in ("name", "cn_name", "en_name", "real_name", "nickname", "role_id"):
        _register_alias(identity.get(key), scope)
    aliases = meta.get("aliases")
    if isinstance(aliases, list):
        for value in aliases:
            _register_alias(value, scope)


def _scan_persona_scopes_impl(configs_dir: Path) -> None:
    if not configs_dir.exists():
        return
    for json_file in sorted(configs_dir.rglob("*.json")):
        try:
            relative = json_file.relative_to(configs_dir)
        except ValueError:
            continue
        if any(part.lower() in {"legacy", "backup"} for part in relative.parts):
            continue
        if json_file.name.startswith("special_") or "reference_dialogue" in json_file.name:
            continue
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if "identity" not in data and "extends" not in data:
            continue
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        if meta.get("deprecated"):
            continue
        _register_persona(json_file, data, configs_dir)


def refresh_scope_registry(configs_dir: Optional[Path] = None) -> None:
    """重新扫描 persona 配置；新增角色后无需修改 Python 角色白名单。"""
    global _ACTIVE_CONFIGS_DIR, _CONFIG_SNAPSHOT, _REGISTRY_INITIALIZED
    global _LAST_CONFIG_CHECK_MONOTONIC

    target = (
        Path(configs_dir).resolve()
        if configs_dir is not None
        else _default_configs_dir()
    )
    with _REGISTRY_LOCK:
        _VALID_SCOPES.clear()
        _VALID_SCOPES.update(_BUILTIN_ROLE_SCOPES | _SPECIAL_SCOPES)
        _DYNAMIC_SCOPES.clear()
        _ISOLATED_SCOPES.clear()
        _PERSONA_SLUG_TO_SCOPE.clear()
        _PERSONA_SLUG_TO_SCOPE.update(_BUILTIN_SLUG_TO_SCOPE)
        _SCOPE_TO_PROFILE_FILENAME.clear()
        _scan_persona_scopes_impl(target)
        _ACTIVE_CONFIGS_DIR = target
        _CONFIG_SNAPSHOT = _config_snapshot(target)
        _LAST_CONFIG_CHECK_MONOTONIC = time.monotonic()
        _REGISTRY_INITIALIZED = True

    if _DYNAMIC_SCOPES and is_debug_enabled("data_paths"):
        logger.info("persona scope 注册完成", scopes=list_dynamic_scopes())


def init_scope_registry() -> None:
    """首次使用时惰性初始化唯一注册表。"""
    if _REGISTRY_INITIALIZED:
        return
    refresh_scope_registry()


def _refresh_if_configs_changed() -> None:
    """alias miss 时限频检查配置变化，避免每次 miss 都扫描全部 persona JSON。"""
    global _LAST_CONFIG_CHECK_MONOTONIC

    init_scope_registry()
    now = time.monotonic()
    with _REGISTRY_LOCK:
        if now - _LAST_CONFIG_CHECK_MONOTONIC < _CONFIG_CHECK_INTERVAL_SECONDS:
            return
        _LAST_CONFIG_CHECK_MONOTONIC = now
        target = _ACTIVE_CONFIGS_DIR or _default_configs_dir()
        snapshot = _CONFIG_SNAPSHOT

    if _config_snapshot(target) != snapshot:
        refresh_scope_registry(target)


def resolve_persona_slug_scope(slug: object) -> str:
    """把 persona 文件名、显示名或别名解析为稳定 scope。"""
    init_scope_registry()
    for candidate in _slug_candidates(slug):
        scope = _PERSONA_SLUG_TO_SCOPE.get(candidate)
        if scope:
            return scope
    _refresh_if_configs_changed()
    for candidate in _slug_candidates(slug):
        scope = _PERSONA_SLUG_TO_SCOPE.get(candidate)
        if scope:
            return scope
    return ""


def resolve_profile_filename_from_scope(scope: Optional[str]) -> str:
    """把稳定 scope 反查为规范 persona 入口文件名（客户端稳定标识）。

    :func:`resolve_persona_slug_scope` 的逆向操作。主动关怀分发在**单角色模式**下
    只有 scope、拿不到 profile_filename，需要靠它补齐 payload 的归属字段，否则
    客户端无法把消息归到具体角色（表现为「有通知、点进去却没有这条消息」）。

    只返回扫描时**真实见过**的入口文件，不凭 scope 名臆造路径；``user`` /
    ``dual_role``、隔离 scope（``persona_<hash>``）与未登记 scope 一律返回空串。
    调用方必须自己回退，不能拿空串去猜一个角色。
    """
    init_scope_registry()
    value = str(scope or "").strip().lower()
    if not value or value in _SPECIAL_SCOPES or value in _ISOLATED_SCOPES:
        return ""
    filename = _SCOPE_TO_PROFILE_FILENAME.get(value, "")
    if filename:
        return filename
    _refresh_if_configs_changed()
    return _SCOPE_TO_PROFILE_FILENAME.get(value, "")


def normalize_data_scope(scope: Optional[str], *, default: str = "user") -> str:
    """归一化显式 scope 或 persona 别名。"""
    init_scope_registry()
    value = str(scope or "").strip().lower()
    if value in _VALID_SCOPES:
        return value
    if value in {
        "default",
        "main",
        "front",
        "assistant",
        "qilai",
        "core_aveline",
    }:
        return "aveline"
    if value in {"ling", "core_ling"}:
        return "ling"
    resolved = resolve_persona_slug_scope(value)
    if resolved:
        return resolved
    return default if default in _VALID_SCOPES else "user"


def _unknown_persona_scope(slug: str) -> str:
    """未知 persona / 无法反解角色的会话 ID 进入稳定隔离 scope。

    必须同步注册进 ``_VALID_SCOPES``：否则 ``normalize_data_scope`` 认不出这个
    scope，会把目录重新塌回默认角色，隔离形同虚设。
    """
    digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:12]
    scope = f"persona_{digest}"
    _VALID_SCOPES.add(scope)
    _ISOLATED_SCOPES.add(scope)
    _DYNAMIC_SCOPES.setdefault(scope, {"dir": f"{scope}_data", "slugs": set()})
    logger.warning(
        "persona 未声明 meta.scope，使用隔离 scope；请补齐配置",
        persona_slug=slug,
        fallback_scope=scope,
    )
    return scope


def resolve_active_persona_scope() -> str:
    """从当前 persona 文件名解析 scope。"""
    try:
        from core.character.managers.persona_manager import get_persona_manager

        current_filename = get_persona_manager().get_current_filename()
        resolved = resolve_persona_slug_scope(current_filename)
        if resolved:
            return resolved
    except Exception:
        if is_debug_enabled("data_paths"):
            logger.info("从活跃 persona 解析 scope 失败", exc_info=True)
    return "aveline"


def resolve_data_scope_from_conversation_id(
    conversation_id: Optional[str],
    *,
    default: str = "aveline",
) -> str:
    """从 conversation_id 解析唯一持久化 scope。"""
    init_scope_registry()
    cid = str(conversation_id or "").strip().lower()
    if not cid:
        return normalize_data_scope(default, default="aveline")
    if "__scope__" in cid:
        scope_part = cid.split("__scope__", 1)[1].strip("_").split("__", 1)[0]
        return normalize_data_scope(scope_part, default=default)
    if cid.startswith("peer_"):
        return "dual_role"
    if cid in {"default", "default_user", "default_local", "default_user_local"}:
        return "user"

    marker = (
        "__persona__"
        if "__persona__" in cid
        else "__circle__"
        if "__circle__" in cid
        else ""
    )
    if marker:
        slug = cid.rsplit(marker, 1)[-1].strip("_").split("__", 1)[0]
        for candidate in cid_slug_candidates(slug):
            resolved = resolve_persona_slug_scope(candidate)
            if resolved:
                return resolved
        return _unknown_persona_scope(slug)

    # 原始 cid 查不到时，按客户端平台前缀剥离后的候选再查一次；
    # 否则 ``web_core_ling`` 这类会话 ID 会塌进默认角色目录，与 aveline 共用记忆。
    for candidate in cid_slug_candidates(cid):
        resolved = resolve_persona_slug_scope(candidate)
        if resolved:
            return resolved

    # 客户端 role 级兜底会话（安卓 ``web_role_<角色名 sha256 前 8 位>``）只含哈希，
    # 无法反解出角色。绝不能塌进任何真实角色目录，否则又会多角色共用一份记忆；
    # 这里给它一个按 cid 稳定的隔离 scope，同一会话每次解析结果一致。
    if _ROLE_DIGEST_CID_PATTERN.match(cid):
        return _unknown_persona_scope(cid)

    return normalize_data_scope(default, default="aveline")


def matched_persona_scope(conversation_id: Optional[str]) -> str:
    """返回会话**真正匹配到**的 persona scope；匹配不到返回空串。

    与 :func:`resolve_data_scope_from_conversation_id` 的区别是不做默认兜底：
    后者在解析不出角色时一律返回 aveline，会让 ``web_sensitive`` 这类与角色无关
    的会话被误判成 aveline。需要「只有确定属于某角色才操作」的场景（例如跨平台
    合并记忆）必须用这个严格版本。
    """
    init_scope_registry()
    lowered = str(conversation_id or "").strip().lower()
    if not lowered:
        return ""

    if "__scope__" in lowered:
        part = lowered.split("__scope__", 1)[1].strip("_").split("__", 1)[0]
        return part if part in get_registered_role_scopes() else ""

    marker = ""
    if "__persona__" in lowered:
        marker = "__persona__"
    elif "__circle__" in lowered:
        marker = "__circle__"
    slug = (
        lowered.rsplit(marker, 1)[-1].strip("_").split("__", 1)[0]
        if marker
        else lowered
    )

    for candidate in cid_slug_candidates(slug):
        resolved = resolve_persona_slug_scope(candidate)
        if resolved in get_registered_role_scopes() and not is_isolated_scope(resolved):
            return resolved
    return ""


def resolve_memory_user_id(conversation_id: Optional[str]) -> str:
    """把会话 ID 归一到记忆主体 ID，实现同一角色的记忆全平台通用。

    QQ 私聊、网页、安卓 App 只要属于同一角色，就归一到
    ``shared__scope__<scope>``，共用同一份记忆。

    群聊 / 双角色互聊 / Telegram 这类会话不是主人的私人记忆，保持各自独立，
    避免把群友的发言或角色间对谈混进私人记忆。

    解析不出角色的会话同样保持原样：宁可各存一份，也不能并进某个角色。
    """
    cid = str(conversation_id or "").strip()
    if not cid:
        return "default"
    if cid.lower().startswith(_NON_MERGEABLE_CID_PREFIXES):
        return cid
    scope = matched_persona_scope(cid)
    if scope:
        return f"shared__scope__{scope}"
    return cid


def resolve_data_scope_from_source(
    source: Optional[str],
    *,
    default: str = "user",
) -> str:
    """从业务 source 或角色别名解析 scope。"""
    raw = str(source or "").strip().lower()
    if raw in {"ling", "ling", "Ling"}:
        return "ling"
    if raw in {
        "aveline",
        "qilai",
        "Aveline",
        "active_care",
        "dual_role",
        "background_circle",
    }:
        return "aveline"
    return normalize_data_scope(raw, default=default)


def get_registered_role_scopes() -> set[str]:
    """返回当前所有角色 scope，不包含 user/dual_role。"""
    init_scope_registry()
    return set(_VALID_SCOPES - _SPECIAL_SCOPES)


def is_isolated_scope(scope: Optional[str]) -> bool:
    """是否是「无法反解出角色」的隔离 scope（``persona_<hash>``）。

    这类 scope 只用于给无角色信息的会话一个独立记忆区，不能反过来覆盖调用方
    已经判断出的角色——否则会把 QQ 群聊等历史会话迁到无主目录。
    """
    init_scope_registry()
    return str(scope or "").strip().lower() in _ISOLATED_SCOPES


def get_dynamic_scope_dir_name(scope: str) -> Optional[str]:
    init_scope_registry()
    info = _DYNAMIC_SCOPES.get(str(scope or "").strip().lower())
    return str(info["dir"]) if info else None


def list_dynamic_scopes() -> dict[str, dict]:
    init_scope_registry()
    return {
        scope: {"dir": info["dir"], "slugs": sorted(info["slugs"])}
        for scope, info in _DYNAMIC_SCOPES.items()
    }


__all__ = [
    "get_dynamic_scope_dir_name",
    "get_registered_role_scopes",
    "init_scope_registry",
    "is_isolated_scope",
    "list_dynamic_scopes",
    "normalize_data_scope",
    "refresh_scope_registry",
    "resolve_active_persona_scope",
    "resolve_data_scope_from_conversation_id",
    "resolve_data_scope_from_source",
    "resolve_memory_user_id",
    "resolve_profile_filename_from_scope",
    "resolve_persona_slug_scope",
]