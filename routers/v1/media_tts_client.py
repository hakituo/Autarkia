# -*- coding: utf-8 -*-
"""TTS 客户端直连配置（仅面向 Android App）。

渠道边界（重要）：
- **Android App**：拿本端点下发的配置直连云端 TTS，音频不经过后端；
  直连不可用时回退 `POST /api/v1/media/tts`。
- **QQ / Telegram 等 Bot 渠道**：仍然只能走后端 `POST /api/v1/media/tts`
  （NapCat 无法访问手机本地文件，也不能持有云端凭据）；QQ 的
  `VoiceService.send_voice_response` 固定请求该路由，本端点不会被它们调用。

安卓端不再把「文本 -> 后端 -> 云端 TTS -> 音频回传」当唯一链路：
只要当前 provider 是云端 TTS，客户端就可以拿着本端点下发的凭据
直接请求云端，少一次音频中转（后端不再负责音频转发）。

下发原则：
- 火山引擎（volcano / volcengine）：appid、api_key、resource_id、cluster、
  voice_map（角色名 -> 音色 ID）、key_map（按音色的独立凭据）、别名表；
- OpenAI 兼容接口（cloud / siliconflow / openai / custom）：base_url、api_key、model；
- 本地引擎（qwen3 / gpt_sovits / f5 ...）客户端无法直连，返回 enabled=False，
  客户端自动回退到 `/api/v1/media/tts`。

安全边界：
- 本端点与其它 /api/v1 接口一样受 security_middleware 保护，只有已鉴权的
  客户端才能拿到凭据；凭据不写日志、不进错误响应。
- 配置 `voice.tts.client_direct=false` 可整体关闭下发（客户端同样回退后端）。
"""

import uuid
from typing import Any, Dict

from core.utils.time_utils import now_iso
from fastapi import APIRouter

from core.api.contract import error_response
from core.api.error_response import ErrorCode

router = APIRouter(prefix="/media", tags=["媒体与语音"])

VOLCANO_PROVIDERS = {"volcano", "volcengine", "字节"}
OPENAI_COMPAT_PROVIDERS = {"cloud", "siliconflow", "openai", "custom"}

VOLCANO_BASE_URL = "https://openspeech.bytedance.com/api/v1/tts"
DEFAULT_VOLCANO_RESOURCE_ID = "volc.megatts.voiceclone"
DEFAULT_VOLCANO_CLUSTER = "volcano_icl"
DEFAULT_VOLCANO_VOICE = "zh_female_qingxin"
DEFAULT_OPENAI_VOICE = "alloy"


def _text(value: Any) -> str:
    """把配置里的各种“空值”统一收敛成空串。"""
    text = str(value or "").strip()
    if text.lower() in {"none", "null", "undefined", "nan"}:
        return ""
    return text


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _str_map(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: Dict[str, str] = {}
    for key, item in value.items():
        name = _text(key)
        target = _text(item)
        if name and target:
            result[name] = target
    return result


def _key_map(value: Any) -> Dict[str, Dict[str, str]]:
    """过滤 key_map，避免把无效条目下发给客户端。"""
    if not isinstance(value, dict):
        return {}
    result: Dict[str, Dict[str, str]] = {}
    for key, item in value.items():
        name = _text(key)
        if not name or not isinstance(item, dict):
            continue
        entry = {
            field: _text(item.get(field))
            for field in ("api_key", "appid")
            if _text(item.get(field))
        }
        if entry:
            result[name] = entry
    return result


def _voice_aliases() -> Dict[str, str]:
    """角色别名 -> 权威音色名（与火山引擎内部解析保持一致）。"""
    try:
        from core.voice.engines.volcano_tts_engine import get_voice_alias_map

        return _str_map(get_voice_alias_map())
    except Exception:
        return {}


def _base_payload(provider: str) -> Dict[str, Any]:
    return {
        "enabled": False,
        "provider": provider,
        "base_url": "",
        "api_key": "",
        "model": "",
        "default_voice": "",
        "reason": "",
    }


def _disabled(payload: Dict[str, Any], reason: str) -> Dict[str, Any]:
    payload["enabled"] = False
    payload["reason"] = reason
    return payload


def _build_volcano_payload(
    tts: Any, extra: Dict[str, Any], payload: Dict[str, Any]
) -> Dict[str, Any]:
    api_key = _text(getattr(tts, "api_key", None))
    # appid 只对旧版鉴权必要；新版 x-api-key 允许为空，因此不作为直连门槛，
    # 与 VolcanoTTSEngine 只校验 api_key 的行为保持一致。
    appid = _text(getattr(tts, "appid", None)) or _text(extra.get("appid"))
    if not api_key:
        return _disabled(payload, "云端 TTS 未配置 api_key")

    voice_map = _str_map(extra.get("voice_map"))
    payload.update(
        {
            "enabled": True,
            "base_url": _text(getattr(tts, "base_url", None)) or VOLCANO_BASE_URL,
            "api_key": api_key,
            "appid": appid,
            "resource_id": _text(extra.get("resource_id"))
            or _text(getattr(tts, "resource_id", None))
            or DEFAULT_VOLCANO_RESOURCE_ID,
            "cluster": _text(extra.get("cluster")) or DEFAULT_VOLCANO_CLUSTER,
            "default_voice": _text(getattr(tts, "model", None)) or DEFAULT_VOLCANO_VOICE,
            "fallback_voice": _text(extra.get("fallback_voice_name")) or "Aveline",
            "encoding": _text(extra.get("encoding")) or "mp3",
            "voice_map": voice_map,
            "key_map": _key_map(extra.get("key_map")),
            "aliases": _voice_aliases(),
        }
    )
    return payload


def _build_openai_payload(
    tts: Any, extra: Dict[str, Any], payload: Dict[str, Any]
) -> Dict[str, Any]:
    api_key = _text(getattr(tts, "api_key", None))
    base_url = _text(getattr(tts, "base_url", None))
    if not api_key:
        return _disabled(payload, "云端 TTS 未配置 api_key")
    if not base_url:
        return _disabled(payload, "云端 TTS 未配置 base_url")

    payload.update(
        {
            "enabled": True,
            "base_url": base_url,
            "api_key": api_key,
            "model": _text(getattr(tts, "model", None)),
            "default_voice": _text(extra.get("default_voice")) or DEFAULT_OPENAI_VOICE,
            "encoding": _text(extra.get("encoding")) or "mp3",
        }
    )
    return payload


def build_direct_config(tts: Any) -> Dict[str, Any]:
    """按 provider 生成客户端直连配置（纯函数，便于单测）。"""
    provider = _text(getattr(tts, "provider", None)).lower()
    extra = getattr(tts, "model_extra", {}) or {}
    if not isinstance(extra, dict):
        extra = {}

    payload = _base_payload(provider)
    if not _as_bool(extra.get("client_direct"), True):
        return _disabled(payload, "后端已关闭客户端直连 TTS")

    if provider in VOLCANO_PROVIDERS:
        return _build_volcano_payload(tts, extra, payload)
    if provider in OPENAI_COMPAT_PROVIDERS:
        return _build_openai_payload(tts, extra, payload)
    return _disabled(payload, "当前 TTS provider 只支持后端合成")


@router.get("/tts/direct-config", summary="TTS 客户端直连配置")
async def tts_direct_config():
    """返回客户端直连云端 TTS 所需的配置；本地引擎返回 enabled=False。"""
    request_id = str(uuid.uuid4())
    try:
        from config.integrated_config import get_settings

        data = build_direct_config(get_settings().voice.tts)
        return {
            "status": "success",
            "data": data,
            "request_id": request_id,
            "timestamp": now_iso(),
        }
    except Exception as exc:  # noqa: BLE001 - 统一转成 API 错误响应
        return error_response(
            ErrorCode.TTS_FAILED,
            message=f"读取 TTS 直连配置失败: {exc}",
            request_id=request_id,
        )
