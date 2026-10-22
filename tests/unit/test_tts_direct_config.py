# -*- coding: utf-8 -*-
"""客户端直连 TTS 配置端点单测。

覆盖：
- 火山 provider 下发 appid/api_key/voice_map 等直连必需字段；
- 本地 provider 明确返回 enabled=False（客户端据此回退后端）；
- `client_direct=false` 可整体关闭下发；
- OpenAI 兼容 provider 缺 base_url 时不下发；
- HTTP 端点返回统一 success 包装。
"""

import asyncio
from types import SimpleNamespace

import routers.v1.media_tts_client as media_tts_client


def _tts(provider: str = "volcano", model_extra=None, **overrides):
    tts = SimpleNamespace(
        provider=provider,
        api_key=overrides.pop("api_key", "test-key"),
        base_url=overrides.pop("base_url", None),
        model=overrides.pop("model", "S_HbG6m9272"),
    )
    for key, value in overrides.items():
        setattr(tts, key, value)
    tts.model_extra = model_extra if model_extra is not None else {}
    return tts


def test_volcano_config_includes_direct_fields():
    tts = _tts(
        model_extra={
            "appid": "app-1",
            "voice_map": {"Aveline": "S_HbG6m9272", "妹妹": "S_IbG6m9272"},
            "key_map": {"妹妹": {"api_key": "other-key", "appid": "app-2"}},
            "resource_id": "volc.megatts.voiceclone",
            "fallback_voice_name": "Aveline",
        }
    )

    data = media_tts_client.build_direct_config(tts)

    assert data["enabled"] is True
    assert data["provider"] == "volcano"
    assert data["appid"] == "app-1"
    assert data["api_key"] == "test-key"
    assert data["base_url"] == media_tts_client.VOLCANO_BASE_URL
    assert data["cluster"] == "volcano_icl"
    assert data["resource_id"] == "volc.megatts.voiceclone"
    assert data["voice_map"]["妹妹"] == "S_IbG6m9272"
    assert data["key_map"]["妹妹"]["api_key"] == "other-key"
    # 别名表与后端引擎同源，避免客户端另抄一份
    assert data["aliases"].get("Aveline") == "Aveline"


def test_volcano_requires_api_key():
    tts = _tts(api_key="", model_extra={"appid": "app-1", "voice_map": {}})

    data = media_tts_client.build_direct_config(tts)

    assert data["enabled"] is False
    assert "api_key" in data["reason"]


def test_volcano_allows_empty_appid():
    """新版 x-api-key 不依赖 appid，缺省时仍应允许直连（与引擎只校验 api_key 一致）。"""
    tts = _tts(model_extra={"voice_map": {"Aveline": "S_HbG6m9272"}})

    data = media_tts_client.build_direct_config(tts)

    assert data["enabled"] is True
    assert data["appid"] == ""


def test_local_provider_is_not_directly_usable():
    data = media_tts_client.build_direct_config(_tts(provider="qwen3"))

    assert data["enabled"] is False
    assert "后端合成" in data["reason"]


def test_client_direct_can_be_disabled():
    data = media_tts_client.build_direct_config(
        _tts(provider="volcano", model_extra={"appid": "app-1", "client_direct": False})
    )

    assert data["enabled"] is False
    assert "已关闭" in data["reason"]


def test_openai_compatible_requires_base_url():
    data = media_tts_client.build_direct_config(_tts(provider="openai", model="tts-1"))

    assert data["enabled"] is False
    assert "base_url" in data["reason"]


def test_openai_compatible_config():
    data = media_tts_client.build_direct_config(
        _tts(provider="siliconflow", base_url="https://api.example.com/v1/audio/speech")
    )

    assert data["enabled"] is True
    assert data["base_url"] == "https://api.example.com/v1/audio/speech"
    assert data["default_voice"] == "alloy"


def test_endpoint_returns_success(monkeypatch):
    fake_settings = SimpleNamespace(
        voice=SimpleNamespace(
            tts=_tts(
                model_extra={"appid": "app-1", "voice_map": {"Aveline": "S_HbG6m9272"}}
            )
        )
    )

    class _ConfigModule:
        @staticmethod
        def get_settings():
            return fake_settings

    import config.integrated_config as integrated_config

    monkeypatch.setattr(integrated_config, "get_settings", _ConfigModule.get_settings)

    resp = asyncio.run(media_tts_client.tts_direct_config())

    assert resp["status"] == "success"
    assert resp["data"]["enabled"] is True
    assert resp["data"]["appid"] == "app-1"
    assert resp["request_id"]
