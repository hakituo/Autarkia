"""分级模式探针：直接打 `/api/v1/plugins/variants/toggle`，不往聊天记录里写探针。

以前手测分级模式是往 `/api/v1/chat` 发 `/sensitive hello`：cid 认不出角色，
`resolve_data_scope_from_conversation_id` 会兜底成 `storage_scope=aveline`，于是每次探针
都落进 aveline 的 chat_history。夜间按段提取会把它们切成一段段
（30 分钟空闲即切），每段必然 `no_reusable_info`，却要白打一次模型，还挤占
「每角色每晚 30 段」的预算（实测 `u1` 攒了 200 多段）。

这个脚本只调插件域接口，不产生聊天事件。

用法：
    venv_cpu/bin/python scripts/tools/probe_sensitive_toggle.py status
    venv_cpu/bin/python scripts/tools/probe_sensitive_toggle.py on
    venv_cpu/bin/python scripts/tools/probe_sensitive_toggle.py off --user-id default
    venv_cpu/bin/python scripts/tools/probe_sensitive_toggle.py on --base-url http://127.0.0.1:8000

退出码：0 = 请求成功；1 = 后端不可用或返回非 2xx。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
TIMEOUT_SECONDS = 10.0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="分级模式探针（不写聊天记录）")
    parser.add_argument("action", choices=("status", "on", "off"), help="查询状态 / 开启 / 关闭")
    parser.add_argument(
        "--base-url", default=DEFAULT_BASE_URL, help=f"服务地址（默认 {DEFAULT_BASE_URL}）"
    )
    parser.add_argument("--user-id", default="default", help="记忆主体 user_id（开关记录写这里）")
    return parser


async def _probe(action: str, base_url: str, user_id: str) -> int:
    base = base_url.rstrip("/")
    async with httpx.AsyncClient(base_url=base, timeout=TIMEOUT_SECONDS) as client:
        if action == "status":
            response = await client.get("/api/v1/plugins/variants/status", params={"user_id": user_id})
        else:
            response = await client.post(
                "/api/v1/plugins/variants/toggle",
                json={"enabled": action == "on", "user_id": user_id},
            )
    payload: object
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 - 非 JSON 响应也照样回显
        payload = response.text[:500]
    print(json.dumps({"status_code": response.status_code, "body": payload}, ensure_ascii=False))
    return 0 if response.is_success else 1


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return asyncio.run(_probe(args.action, args.base_url, args.user_id))
    except httpx.HTTPError as exc:
        print(f"请求失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
