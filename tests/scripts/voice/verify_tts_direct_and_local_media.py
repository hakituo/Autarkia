# -*- coding: utf-8 -*-
"""验证「客户端直连云端 TTS + 聊天媒体本地优先」两条链路的静态接线。

背景：这两条链路的共同点是「后端提供配置 / 客户端负责落地」，最容易出的问题是
改后端忘了改客户端、或路由聚合时漏挂载，单测又跑不到 Android 侧。这里做四件事：

1. 路由挂载：/media/tts/direct-config 已注册到聚合 router；
2. 配置生成：云端 provider 下发必要字段，本地 provider 明确 disabled；
3. Android 直连：TTSEngine 调 CloudTtsSynthesizer，失败回退后端；
4. Android 本地媒体：图片/视频组件走 rememberLocalMediaFile，收到即 prefetch。

用法：
    venv_cpu/bin/python tests/scripts/voice/verify_tts_direct_and_local_media.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
ANDROID = (
    ROOT
    / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"
)

CHECKS: list[tuple[bool, str]] = []


def check(ok: bool, name: str) -> None:
    CHECKS.append((bool(ok), name))


def read(relative: str) -> str:
    path = ANDROID / relative
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def verify_route() -> None:
    from routers.v1.media import router

    paths = {getattr(route, "path", "") for route in router.routes}
    check("/media/tts" in paths, "既有 /media/tts 路由仍存在（回退链路）")
    check("/media/tts/direct-config" in paths, "直连配置路由已挂载")


def verify_config() -> None:
    import routers.v1.media_tts_client as api

    volcano = SimpleNamespace(
        provider="volcano",
        api_key="k",
        base_url=None,
        model="S_HbG6m9272",
        appid="app",
        model_extra={"voice_map": {"Aveline": "S_HbG6m9272"}},
    )
    data = api.build_direct_config(volcano)
    check(data["enabled"] is True, "火山 provider 下发 enabled=True")
    check(data["appid"] == "app", "火山 provider 下发 appid")
    check(data["voice_map"]["Aveline"] == "S_HbG6m9272", "火山 provider 下发 voice_map")

    local = api.build_direct_config(
        SimpleNamespace(provider="qwen3", api_key="", base_url=None, model="", model_extra={})
    )
    check(local["enabled"] is False, "本地 provider 返回 enabled=False（客户端回退后端）")


def verify_android_tts() -> None:
    engine = read("services/TTSEngine.kt")
    client = read("services/tts/CloudTtsSynthesizer.kt")
    api = read("data/remote/api/AvelineApiService.kt")

    check("CloudTtsSynthesizer" in engine, "TTSEngine 注入直连合成器")
    check("synthesizeDirect" in engine, "TTSEngine 先尝试直连")
    check("apiService.synthesizeTTS" in engine, "TTSEngine 保留后端回退")
    check("audioCache.find" in engine, "重复播放先查音频缓存")
    check("TtsAudioCache" in engine, "音频缓存抽成独立模块")
    check("CoroutineExceptionHandler" in engine, "TTS 协程有兜底，不允许闪退")
    check("catch (t: Throwable)" in engine, "播放链路捕获 Throwable 而非仅 Exception")
    check('GET("/api/v1/media/tts/direct-config")' in api, "Android API 声明直连配置端点")
    check("x-api-key" in client, "火山直连使用 x-api-key 鉴权")
    check("X-Api-Resource-Id" in client, "火山直连携带资源 ID")
    check("normalizeSpeechUrl" in client, "OpenAI 兼容语音端点补全")

    # Android ICU 正则不接受裸 `}`：曾因 TtsTextSanitizer 里 `\{[^}]*}` 在类初始化时
    # 抛 PatternSyntaxException -> ExceptionInInitializerError，点播放语音必闪退
    sanitizer = read("services/tts/TtsTextSanitizer.kt")
    check("\\\\}" in sanitizer, "括号正则右大括号已转义（ICU 要求）")
    check("{[^}]*}" not in sanitizer, "不存在裸 } 的正则（防闪退回归）")


def verify_bot_channels() -> None:
    """QQ / Telegram 必须继续走后端 /api/v1/media/tts，不能被直连改造带偏。"""
    qq_voice = (ROOT / "clients/bots/qq/voice_service.py").read_text(
        encoding="utf-8", errors="ignore"
    )
    tg_media = (ROOT / "clients/bots/telegram/media_sender.py").read_text(
        encoding="utf-8", errors="ignore"
    )
    media_voice = (ROOT / "routers/v1/media_voice.py").read_text(
        encoding="utf-8", errors="ignore"
    )

    check('"/api/v1/media/tts"' in qq_voice, "QQ VoiceService 仍请求后端 /media/tts")
    check("direct-config" not in qq_voice, "QQ 不消费客户端直连配置")
    check('"/api/v1/media/tts"' in tg_media, "Telegram 仍请求后端 /media/tts")
    check('@router.post("/tts"' in media_voice, "后端 /media/tts 合成端点保留")
    check("generate_tts_with_async" in media_voice, "后端合成核心未被直连改造替换")


def verify_android_media() -> None:
    store = read("services/media/LocalMediaStore.kt")
    model = read("presentation/components/LocalMediaModel.kt")
    bubble = read("presentation/components/MessageBubble.kt")
    video = read("presentation/components/VideoMessageBubble.kt")
    incoming = read("presentation/chat/ChatIncomingMessageHandler.kt")

    check("filesDir" in store, "本地媒体落在私有 filesDir（不是 cacheDir）")
    check("stableKey" in store, "媒体 key 与后端地址无关")
    check("Authorization" in store and "x-internal-token" in store, "下载媒体携带后端鉴权头")
    check("rememberLocalMediaFile" in bubble, "图片组件本地优先")
    check("rememberLocalMediaFile" in video, "视频/动图组件本地优先")
    check("LocalMediaStore" in model, "Composable 通过 EntryPoint 获取单例")
    check("localMediaStore?.prefetch" in incoming, "WS 收到图片/动图即落盘")
    # SSE 通道的预取已由并行改动摘除（d1d9dc24）：用户主动发消息产生的图片会立刻
    # 上屏渲染，由 rememberLocalMediaFile 在渲染时兜底落盘，因此这里只断言渲染层。
    check("rememberLocalMediaFile" in bubble, "SSE 图片由渲染层本地优先兜底落盘")


def main() -> int:
    verify_route()
    verify_config()
    verify_android_tts()
    verify_android_media()
    verify_bot_channels()

    failed = [name for ok, name in CHECKS if not ok]
    for ok, name in CHECKS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} 项通过")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
