"""验证「轻问候开场 + 议程一步步带」整条链路（2026-10-28）。

不调用任何模型，议程文件写到临时目录：
1. 决策 prompt 里有【可带的话题】菜单与发送方式指引；
2. 决策出口（工具调用）带 style / topic_id → send plan 走 agenda_opener；
3. 开场白送达后写入议程；主聊天按轮数推进引导文本；
4. close_agenda 只在有议程时可见，且各正式角色的工具权限都放行；
5. 模型调用 close_agenda 后议程结束、工具不再挂。

用法：venv_cpu/bin/python tests/scripts/active_care/verify_agenda_opener_flow.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  ✓ " if cond else "  ✗ ") + label)
    if not cond:
        FAILURES.append(label)


RANKED = [
    {"id": "plan:a1", "title": "计划项：[14:45] 化学 · 氧化还原反应（化学）",
     "suggested_intent": "planned_topic", "reason": "plan_item"},
    {"id": "study:review_due", "title": "学习复习提醒：8个知识点到期",
     "suggested_intent": "planned_topic", "detail": "物理·恒定电流"},
]


async def main() -> int:
    from core.services.active_care.agenda import paths

    tmp = Path(tempfile.mkdtemp(prefix="agenda_verify_"))
    paths.agenda_file = lambda scope: tmp / scope / "agenda.json"

    from core.agents.chat_agent_components.streaming_pipeline.agenda_probes import (
        _probe_active_care_agenda,
    )
    from core.services.active_care import agenda as ag
    from core.services.active_care.agenda.send_plan import build_send_plan, open_agenda_for_plan
    from core.services.active_care.agenda.topics import build_topic_menu, format_topic_menu
    from core.services.active_care.decision.action_protocol import (
        decision_action_to_dict,
        parse_terminal_tool_call,
    )
    from core.services.active_care.prompt.decision_prompt_builder import (
        build_active_care_decision_prompt,
    )
    from core.tools.close_agenda_tool import CloseAgendaTool, close_agenda_tool_names

    print("1. 决策 prompt")
    menu = build_topic_menu(RANKED)
    bundle = build_active_care_decision_prompt(
        chosen_action="planned_topic", llm_ctx={"now": "x"}, dynamic_constraints=[],
        daily_push_text=format_topic_menu(menu),
    )
    check("【可带的话题】" in bundle.user_message and "topic_id=plan:a1" in bundle.user_message,
          "user 消息带话题菜单")
    check("greeting" in bundle.system_prompt and "direct" in bundle.system_prompt,
          "system 带发送方式指引")

    print("2. 决策出口 → send plan")
    decision = decision_action_to_dict(parse_terminal_tool_call(
        "send_active_care", {"reason_code": "plan", "style": "greeting", "topic_id": "plan:a1"},
        intent="planned_topic",
    ))
    decision["topic_menu"] = menu
    plan = build_send_plan(decision, intent="planned_topic", specific_instruction="",
                           recent_opener_texts=["在不"])
    check(plan.sys_prompt_type == "agenda_opener", "greeting → agenda_opener")
    check("在不" in plan.specific_instruction, "开场白去重提示带上最近用过的")

    print("3. 开场白送达 → 议程 → 主聊天推进")
    check(await close_agenda_tool_names("web_role_aveline") == [], "开场前不挂 close_agenda")
    await open_agenda_for_plan("aveline", plan, intent="planned_topic", opener_text="在干嘛呢")
    texts = []
    for _ in range(6):
        text, commit = await _probe_active_care_agenda({"user_id": "web_role_aveline"})
        texts.append(text)
        await commit()
    check("不要提这件事" in texts[0], "第 1 轮：先接话、不提")
    check("自然的切口" in texts[2], "第 3 轮：找切口")
    check("轻轻带一句" in texts[5], "第 6 轮：可以轻轻带一句")
    check("化学 · 氧化还原反应" in texts[0] and "在干嘛呢" in texts[0], "注入里有话题和开场白")
    group = await _probe_active_care_agenda({"user_id": "group_1_2__persona__core_aveline"})
    check(group == ("", None), "群聊不注入")

    print("4. close_agenda 可见性")
    check(await close_agenda_tool_names("web_role_aveline") == ["close_agenda"], "有议程时挂上")
    from core.tools.registry import ToolRegistry, register_all_tools
    from core.tools.tool_visibility import filter_tool_names

    registry = ToolRegistry()
    register_all_tools(registry)
    check(registry.get_tool("close_agenda") is not None, "close_agenda 已注册")
    for persona in ("core_aveline.json", "core_ling.json", "core_ye.json"):
        kept = filter_tool_names(["close_agenda"], tool_registry=registry,
                                 profile_filename=persona, mode="chat", is_sensitive_mode=False)
        check(kept == ["close_agenda"], f"{persona} 工具权限放行")

    print("5. 模型结束议程")
    tool = CloseAgendaTool()
    tool.set_runtime_context({"user_id": "web_role_aveline"})
    await tool._run(reason="doing")
    check(await ag.get_active_agenda("aveline") is None, "议程已结束")
    check(await close_agenda_tool_names("web_role_aveline") == [], "结束后不再挂工具")

    print()
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：", "；".join(FAILURES))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
