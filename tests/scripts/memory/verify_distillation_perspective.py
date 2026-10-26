"""验证记忆蒸馏的角色归属、第一人称 prompt 与角色白名单。

改造前只有一套「记忆管理专家」中立模板，梗概写成「用户表示……助手回复……」。
改造后从记忆归属认角色（会话 ID 里的角色标识 → 严格注册 scope → 落盘目录），
用该角色第一人称写；认不出就回中立模板、绝不借别人的口吻；且只蒸馏白名单角色
（当前只有 aveline，先在 Aveline 身上调参）。本脚本不发送真实 LLM 请求。运行：
    venv_cpu\\Scripts\\python.exe -m tests.scripts.memory.verify_distillation_perspective
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


class _Manager:
    """最小记忆管理器：归属标识、锁、记忆表与落盘接口。"""

    def __init__(
        self,
        scope: str,
        memories: Optional[Dict[str, Dict[str, Any]]] = None,
        user_id: str = "",
    ) -> None:
        self.storage_scope = scope
        self.user_id = user_id
        self.lock = threading.RLock()
        self.weighted_memories = dict(memories or {})
        self.updates: List[Dict[str, Any]] = []

    def update_memory_distillation(
        self, memory_id: str, summary: str, keywords: List[str], **_kwargs: Any
    ) -> bool:
        self.updates.append({"id": memory_id, "summary": summary, "keywords": keywords})
        return True


async def _chunks(text: str):
    yield text


class _Scheduler:
    """记录每次调用的 prompt，并按预设顺序返回响应（异常项直接抛出）。"""

    def __init__(self, responses: Optional[List[Any]] = None) -> None:
        self._responses = list(responses or [])
        self.calls: List[Dict[str, Any]] = []

    def submit_llm_task(self, prompt: Any, **kwargs: Any) -> Any:
        self.calls.append({"prompt": prompt, **kwargs})
        if not self._responses:
            return _chunks("")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return _chunks(str(response))


def _memories() -> Dict[str, Dict[str, Any]]:
    """两条待蒸馏记忆：一条他说、一条我说，时间相邻。"""
    ts = time.time() - 7200
    return {
        "m1": {
            "id": "m1",
            "role": "user",
            "content": "今天又被派去改那个报表了，改到八点多才走。",
            "timestamp": ts,
            "is_distilled": False,
        },
        "m2": {
            "id": "m2",
            "role": "assistant",
            "content": "改到八点多？你中午是不是又没顾上吃饭，胃又要疼了。",
            "timestamp": ts + 30,
            "is_distilled": False,
        },
    }


def _batch_response(count: int = 2) -> str:
    return "\n\n".join(
        f"【条目{i}】\n【梗概】：他抱怨报表改到八点多，我问他中午吃饭没有\n"
        "【关键词】：报表,加班,吃饭\n【人物线索】：无\n【角色演化】：无"
        for i in range(1, count + 1)
    )


def _run_distill(
    scope: str,
    memories: Dict[str, Dict[str, Any]],
    scheduler: _Scheduler,
    whitelist: Optional[List[str]] = None,
) -> _Manager:
    from memory.nightly.config import DEFAULT_NIGHTLY_CONFIG
    from memory.nightly.task_runner import NightlyTaskRunner

    manager = _Manager(scope, memories, user_id=f"shared__scope__{scope}")
    config = dict(DEFAULT_NIGHTLY_CONFIG)
    config["distillation_role_whitelist"] = list(whitelist or [scope])
    runner = NightlyTaskRunner(config)
    target = "memory.nightly.task_runner.get_global_scheduler"
    with patch(target, return_value=scheduler):
        asyncio.run(runner.distill_memories_async(scope, manager))
    return manager


def verify_perspective_resolution() -> None:
    """按会话/落盘归属认出角色；认不出就回中立，绝不借别人的口吻。"""
    from memory.nightly.perspective import resolve_distillation_perspective

    recognized = {
        "shared__scope__aveline": "Aveline",
        "shared__scope__ling": "Ling",
        "shared__scope__rushuang": "Frost",
        "private_123456789__persona__yeye": "Coco",
        "private_123456789": "Aveline",
    }
    for conversation_id, role_name in recognized.items():
        perspective = resolve_distillation_perspective(
            _Manager("aveline", user_id=conversation_id)
        )
        _assert(
            perspective.get("role_name") == role_name
            and bool(perspective.get("user_name"))
            and bool(perspective.get("role_profile")),
            f"{conversation_id} 认到 {role_name} 的完整视角",
        )

    for conversation_id in ("shared__scope__chiba", "shared__scope__kafka"):
        _assert(
            resolve_distillation_perspective(
                _Manager("aveline", user_id=conversation_id)
            )
            == {},
            f"{conversation_id} 没有对应人设时回中立，不借 Aveline 的口吻",
        )

    for scope, expected in (
        ("aveline", "Aveline"),
        ("ling", "Ling"),
        ("user", ""),
        ("dual_role", ""),
    ):
        name = resolve_distillation_perspective(_Manager(scope)).get("role_name", "")
        _assert(name == expected, f"只有 storage_scope={scope} 时解析为 {expected or '中立'}")


def verify_persona_batch_prompt() -> None:
    """批量 prompt 用角色第一人称，说话者换成人名，system 跨批一致。"""
    from memory.nightly.perspective import (
        build_batch_distillation_prompt,
        resolve_distillation_perspective,
    )

    perspective = resolve_distillation_perspective(_Manager("ling"))
    user_name = perspective["user_name"]
    messages = [
        {"id": "m1", "role": "user", "content": "今天又被派去改那个报表"},
        {"id": "m2", "role": "assistant", "content": "改到几点，别又拖到半夜"},
    ]
    built = build_batch_distillation_prompt(messages, perspective)
    system, user_content = built[0]["content"], built[1]["content"]

    _assert("Ling" in system and user_name in system, "system 声明我是谁、对方是谁")
    _assert(
        "第一人称" in system and "不要「用户」「助手」" in system,
        "system 要求第一人称且禁止旁观者称呼",
    )
    _assert(
        "{role_name}" not in system and "{user_name}" not in system,
        "system 占位符全部填充",
    )
    _assert(f"【说话者】{user_name}" in user_content, "他说的话标成对话者")
    _assert("【说话者】Ling" in user_content, "自己说的话标成角色本人")

    other = build_batch_distillation_prompt(
        [{"id": "m3", "role": "user", "content": "另一段完全不同的内容"}],
        perspective,
    )
    _assert(other[0]["content"] == system, "system 跨批逐字一致（缓存前缀不变）")


def verify_neutral_fallback() -> None:
    """解析不出角色时逐字退回原中立模板，说话者保持原样。"""
    from core.agents.chat_agent_components.persona_system.prompt.service_prompts import (
        MEMORY_DISTILLATION_BATCH_SYSTEM_PROMPT,
        MEMORY_DISTILLATION_SYSTEM_PROMPT,
    )
    from memory.nightly.task_runner import NightlyTaskRunner

    batch = NightlyTaskRunner.generate_batch_distillation_prompt(
        [{"id": "m1", "role": "user", "content": "普通测试内容一段"}]
    )
    single = NightlyTaskRunner.generate_distillation_prompt("普通测试内容一段")
    _assert(
        batch[0]["content"] == MEMORY_DISTILLATION_BATCH_SYSTEM_PROMPT
        and single[0]["content"] == MEMORY_DISTILLATION_SYSTEM_PROMPT
        and "【说话者】user" in batch[1]["content"],
        "无视角时逐字退回原中立模板、说话者保持原样",
    )


def verify_persona_voice_and_whitelist() -> None:
    """批量与失败回退都带角色视角；不在白名单的角色一次都不蒸馏。"""
    from memory.nightly.config import (
        DEFAULT_NIGHTLY_CONFIG,
        is_distillation_role_allowed,
    )

    scheduler = _Scheduler([_batch_response()])
    manager = _run_distill("ye", _memories(), scheduler)
    batch_prompt = scheduler.calls[0]["prompt"]
    _assert(
        len(scheduler.calls) == 1 and len(manager.updates) == 2,
        "两条相邻记忆合并为一次请求并全部落盘",
    )
    _assert("Ye" in batch_prompt[0]["content"], "Ye scope 的 system 使用Ye视角")
    _assert("【说话者】Ye" in batch_prompt[1]["content"], "Ye自己的消息标成Ye")

    single = (
        "【梗概】：他说报表改到八点多\n【关键词】：报表,加班\n"
        "【人物线索】：无\n【角色演化】：无"
    )
    fallback = _Scheduler([RuntimeError("批量请求失败"), single, single])
    _run_distill("ling", _memories(), fallback)
    _assert(len(fallback.calls) == 3, "批量 1 次 + 回退 2 次")
    _assert(
        "Ling" in fallback.calls[1]["prompt"][0]["content"], "回退单条使用Ling视角"
    )

    blocked = _Scheduler()
    skipped = _run_distill("ling", _memories(), blocked, whitelist=["aveline"])
    _assert(
        not blocked.calls and not skipped.updates,
        "白名单只放 aveline 时Ling scope 0 请求 0 落盘",
    )
    _assert(
        is_distillation_role_allowed(DEFAULT_NIGHTLY_CONFIG, "aveline")
        and not is_distillation_role_allowed(DEFAULT_NIGHTLY_CONFIG, "ling"),
        "默认白名单只有 aveline",
    )


def verify_local_signal_and_role_candidates() -> None:
    """本地零 API 规则认所有已注册角色；角色演化线索只留角色名。"""
    from core.character.people.signal_gate import PeopleProfileSignalGate
    from memory.nightly.task_runner import NightlyTaskRunner

    metadata = NightlyTaskRunner.detect_profile_signals_locally(
        "我其实不太喜欢人多的场合", role="assistant", owner_role_id="ye"
    )
    _assert(
        metadata["role_update_candidates"] == ["ye"],
        "Ye本人的持久偏好也进角色演化线索",
    )
    gate = PeopleProfileSignalGate.detect_local_signals(
        {"role": "ye", "content": "我最近习惯了早睡"}
    )
    _assert(bool(gate["role_updates"]), "本地门控认得Ye这个说话者")
    user_side = NightlyTaskRunner.detect_profile_signals_locally(
        "我最近习惯了早睡", role="user", owner_role_id="ye"
    )
    _assert(not user_side["role_update_candidates"], "用户说的话不算角色本身的偏好")
    parsed = NightlyTaskRunner.parse_profile_signals(
        "【梗概】：他八点多才走\n【关键词】：加班\n"
        "【人物线索】：张老师\n【角色演化】：Aveline：习惯嘴上嫌弃，实际很在意"
    )
    _assert(
        parsed["role_update_candidates"] == ["Aveline"],
        "角色演化只保留角色名，解释性文字被丢弃",
    )


def main() -> int:
    verify_perspective_resolution()
    verify_persona_batch_prompt()
    verify_neutral_fallback()
    verify_persona_voice_and_whitelist()
    verify_local_signal_and_role_candidates()
    print("\n[PASS] 记忆蒸馏角色视角与白名单验证全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
