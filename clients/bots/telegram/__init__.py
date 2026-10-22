# Telegram Adapter Package
#
# adapter / session 链路依赖 python-telegram-bot（可选依赖）。包级 __init__ 若急切导入，
# 即使 app.yaml 里 telegram.enabled=false 也会在启动时抛 ModuleNotFoundError，
# 因此这里只保留无第三方依赖的 settings，其余符号按需延迟导入。
from clients.bots.telegram.settings import logger

__all__ = [
    "TelegramAdapter",
    "TelegramSession",
    "HttpClient",
    "HealthChecker",
    "build_persona_conversation_id",
    "run_adapter",
    "logger",
]


def __getattr__(name):
    if name in ("TelegramAdapter", "run_adapter"):
        from clients.bots.telegram.adapter import TelegramAdapter, run_adapter

        return {"TelegramAdapter": TelegramAdapter, "run_adapter": run_adapter}[name]
    if name in ("HttpClient", "HealthChecker"):
        from clients.bots.telegram.http_client import HttpClient, HealthChecker

        return {"HttpClient": HttpClient, "HealthChecker": HealthChecker}[name]
    if name in ("TelegramSession", "build_persona_conversation_id"):
        from clients.bots.telegram.session import (
            TelegramSession,
            build_persona_conversation_id,
        )

        return {
            "TelegramSession": TelegramSession,
            "build_persona_conversation_id": build_persona_conversation_id,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
