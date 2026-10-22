# -*- coding: utf-8 -*-
"""角色资料（roles）域。

网页端要从「单会话」升级成「多角色会话」，就需要一份稳定的角色清单：
显示名、头像、音色，以及对应的人设文件名。这些信息散落在
``core/character/configs/**/core_*.json`` 的 ``name`` / ``meta.scope`` 里，
用户在客户端改过的昵称/头像/音色则保存在 ``companion_data/role_profiles.json``。

角色清单只返回 scope 注册表里已登记的角色，避免把 ``variants/`` 等
私有目录下的名字透出去。

GET /roles
GET /roles/{scope}
PUT /roles/{scope}
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Path as ApiPath
from pydantic import BaseModel, Field

from core.api.contract import error_response, success_response
from core.api.error_response import ErrorCode
from core.utils.atomic_io import async_safe_json_dump, async_safe_json_load
from core.utils.data.scope_registry import get_registered_role_scopes
from core.utils.logger import get_logger
from core.utils.project_root import get_project_root

logger = get_logger("ROLE_PROFILE_ROUTER")

router = APIRouter(prefix="/roles", tags=["角色资料"])

_CONFIG_DIR = Path("core") / "character" / "configs"
_OVERRIDE_FILE = Path("companion_data") / "role_profiles.json"
_SCOPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_NAME_LENGTH = 40
_MAX_AVATAR_LENGTH = 512


class RoleProfileUpdate(BaseModel):
    """角色资料的可编辑字段，未传的字段保持原值。"""

    display_name: Optional[str] = Field(default=None, description="角色昵称")
    avatar: Optional[str] = Field(default=None, description="头像地址或 emoji")
    voice_id: Optional[str] = Field(default=None, description="音色名（/media/voices 返回的 id）")


def _config_root() -> Path:
    return get_project_root() / _CONFIG_DIR


def _override_path() -> Path:
    return get_project_root() / _OVERRIDE_FILE


async def _read_overrides() -> Dict[str, Dict[str, Any]]:
    data = await async_safe_json_load(_override_path(), default={})
    return data if isinstance(data, dict) else {}


async def _write_overrides(data: Dict[str, Dict[str, Any]]) -> None:
    path = _override_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    await async_safe_json_dump(data, path)


def _scan_role_configs_sync() -> Dict[str, Dict[str, Any]]:
    """扫描人设配置，返回 scope -> 基础资料（同 scope 取第一个命中）。"""
    root = _config_root()
    result: Dict[str, Dict[str, Any]] = {}
    if not root.exists():
        return result

    for path in sorted(root.rglob("core_*.json")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        scope = str(meta.get("scope") or path.parent.name).strip().lower()
        if not _SCOPE_PATTERN.match(scope) or scope in result:
            continue
        aliases = meta.get("aliases") if isinstance(meta.get("aliases"), list) else []
        profile = meta.get("context_profile") if isinstance(meta.get("context_profile"), dict) else {}
        result[scope] = {
            "scope": scope,
            "name": str(payload.get("name") or scope),
            "aliases": [str(item) for item in aliases if str(item).strip()],
            "persona_file": path.name,
            "voice_file": str(profile.get("voice") or ""),
            "config_relative_path": str(path.relative_to(get_project_root())),
        }
    return result


def _merge_profile(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    display_name = str(override.get("display_name") or "").strip()
    merged["display_name"] = display_name or base.get("name") or base.get("scope")
    merged["avatar"] = str(override.get("avatar") or "").strip()
    merged["voice_id"] = str(override.get("voice_id") or "").strip()
    merged["overridden"] = bool(display_name or merged["avatar"] or merged["voice_id"])
    return merged


async def _collect_roles() -> List[Dict[str, Any]]:
    import asyncio

    registered = get_registered_role_scopes()
    configs = await asyncio.to_thread(_scan_role_configs_sync)
    overrides = await _read_overrides()
    roles: List[Dict[str, Any]] = []
    for scope, base in configs.items():
        if registered and scope not in registered:
            continue
        override = overrides.get(scope) if isinstance(overrides.get(scope), dict) else {}
        roles.append(_merge_profile(base, override))
    roles.sort(key=lambda item: str(item.get("scope")))
    return roles


@router.get("", summary="获取角色清单")
async def list_roles():
    try:
        roles = await _collect_roles()
        return success_response(data={"roles": roles, "total": len(roles)})
    except Exception as exc:  # pragma: no cover - 兜底分支
        logger.error(f"获取角色清单失败: {exc}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(exc))


@router.get("/{scope}", summary="获取单个角色资料")
async def get_role(scope: str = ApiPath(..., description="角色 scope")):
    normalized = str(scope or "").strip().lower()
    if not _SCOPE_PATTERN.match(normalized):
        return error_response(ErrorCode.INVALID_PARAMETER, message="角色 scope 非法")
    try:
        roles = await _collect_roles()
        for role in roles:
            if role.get("scope") == normalized:
                return success_response(data={"role": role})
        return error_response(ErrorCode.RESOURCE_NOT_FOUND, message=f"角色不存在: {normalized}")
    except Exception as exc:  # pragma: no cover - 兜底分支
        logger.error(f"获取角色资料失败: {exc}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(exc))


@router.put("/{scope}", summary="更新角色昵称/头像/音色")
async def update_role(
    scope: str = ApiPath(..., description="角色 scope"),
    payload: RoleProfileUpdate = Body(...),
):
    normalized = str(scope or "").strip().lower()
    if not _SCOPE_PATTERN.match(normalized):
        return error_response(ErrorCode.INVALID_PARAMETER, message="角色 scope 非法")

    display_name = (payload.display_name or "").strip()
    avatar = (payload.avatar or "").strip()
    voice_id = (payload.voice_id or "").strip()
    if len(display_name) > _MAX_NAME_LENGTH:
        return error_response(ErrorCode.INVALID_PARAMETER, message="昵称过长")
    if len(avatar) > _MAX_AVATAR_LENGTH:
        return error_response(ErrorCode.INVALID_PARAMETER, message="头像地址过长")

    try:
        roles = await _collect_roles()
        base = next((role for role in roles if role.get("scope") == normalized), None)
        if base is None:
            return error_response(
                ErrorCode.RESOURCE_NOT_FOUND, message=f"角色不存在: {normalized}"
            )

        overrides = await _read_overrides()
        current = overrides.get(normalized) if isinstance(overrides.get(normalized), dict) else {}
        next_profile = dict(current)
        if payload.display_name is not None:
            next_profile["display_name"] = display_name
        if payload.avatar is not None:
            next_profile["avatar"] = avatar
        if payload.voice_id is not None:
            next_profile["voice_id"] = voice_id
        overrides[normalized] = next_profile
        await _write_overrides(overrides)

        return success_response(
            data={"role": _merge_profile(base, next_profile)}, message="角色资料已更新"
        )
    except Exception as exc:  # pragma: no cover - 兜底分支
        logger.error(f"更新角色资料失败: {exc}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(exc))


__all__ = ["router"]
