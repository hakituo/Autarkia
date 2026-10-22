#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""即时私聊口径的三道闸（防回归）。

背景（2026-10-16）：加了日常活动之后，所有角色在「正在做事」时被发消息，都会先
报备自己在干什么，而且话多、爱在答完后追加「你呢」。根因不在人设层，而在三处：

1. ``soft_reply_char_limit`` 一路算出来、传到底，但 ``EmotionManager._resolve_length``
   **只有定义没有调用点**，字数上限从未进过 prompt；
2. 被动回复侧有模板在**命令**角色提及自己在做什么
   （``_BUSY_DONE_TEMPLATE`` / ``_MORNING_AFTER_TEMPLATE`` /
   ``build_manual_interrupt_window_hint``）；
3. 反查岗约束只存在于主动关怀链路，全局静态层什么都没有。

本文件把这三处的判据钉住；改 prompt 时别把这些断言删掉。
"""


def test_resolve_length_renders_small_limit():
    from core.emotion.manager import EmotionManager

    assert (
        EmotionManager._resolve_length(50, None)
        == "回复请尽量保持在50字以内，保持自然，不要刻意截断。"
    )


def test_resolve_length_skips_no_cap_tier():
    """1000 是「不限制」档，不该再往 prompt 里塞一句等于没说的话。"""
    from core.emotion.manager import EmotionManager

    assert EmotionManager._resolve_length(1000, None) == ""


def test_resolve_length_falls_back_to_max_tokens():
    from core.emotion.manager import EmotionManager

    assert EmotionManager._resolve_length(None, 100) == "回复请保持简短自然，不要刻意截断句子。"
    assert EmotionManager._resolve_length(None, 300) == "回复请保持简洁，控制在80字左右。"
    assert EmotionManager._resolve_length(None, 900) == "回复可以详细一些，不需要刻意控制字数，多说一点。"
    assert EmotionManager._resolve_length(None, None) == ""


def test_affect_instruction_carries_length_rule():
    """长度上限必须真的落进 prompt —— 之前它被静默丢弃。"""
    from core.emotion.manager import EmotionManager

    mgr = EmotionManager(config={"enabled": True, "affect_prompt_enabled": True})
    text = mgr.build_dialogue_affect_instruction(user_id="", soft_reply_char_limit=50)
    assert "50字以内" in text


def test_affect_instruction_without_limit_has_no_length_rule():
    from core.emotion.manager import EmotionManager

    mgr = EmotionManager(config={"enabled": True, "affect_prompt_enabled": True})
    assert "字以内" not in mgr.build_dialogue_affect_instruction(user_id="")


def test_infer_soft_reply_limit_keeps_study_uncapped():
    """study 不能被短回复口径掐死：``mode`` 入参以前完全没用。"""
    from core.agents.chat_agent_components.stream_utils import StreamContextBuilder

    assert StreamContextBuilder.infer_soft_reply_limit("study", False, False, "讲讲这道题") >= 1000
    assert StreamContextBuilder.infer_soft_reply_limit("chat", False, False, "在吗") == 50


def test_reply_hints_do_not_force_activity_report():
    """被动回复侧不得再命令角色「必须提及自己在做什么」，只能给可选措辞。"""
    from core.services.character_daily.reply_hints import (
        build_busy_done_hint,
        build_morning_after_hint,
    )

    done = build_busy_done_hint(["在吗"], activity_verb="学习")
    assert "刚做完xx" in done  # 仍提供可选措辞
    assert "自然地提到" not in done  # 但不再是命令
    assert "提不提" in done

    morning = build_morning_after_hint(["在吗"])
    assert "刚醒" in morning
    assert "自然地提到" not in morning
    assert "提不提" in morning


def test_manual_interrupt_hint_does_not_force_activity_report():
    from core.services.character_daily.activity_model import ActivityType
    from core.services.character_daily.reply_policy_support import (
        build_manual_interrupt_window_hint,
    )

    hint = build_manual_interrupt_window_hint(ActivityType.STUDYING, 30.0)
    assert "你需要在这条回复里自然地提及" not in hint
    assert "不要完全不提" not in hint
    assert "由你按当前聊天氛围决定" in hint


def test_global_prefix_carries_im_style_rule():
    """全局固定层必须承担「短对话 + 不报备 + 不机械反问」这三条。"""
    from core.agents.chat_agent_components.persona_system.prompt.fixed_prefix import (
        get_fixed_prefix,
    )

    text = get_fixed_prefix()
    assert "即时通讯基本法" in text
    assert "你呢" in text
    assert "背景事实" in text
    # 学习场景必须留出例外，否则接回字数上限会把讲解一起掐死
    assert "不受以上长度限制" in text
    # 短句要分行，不能拿逗号把两个意思串成一句（用户实际聊天几乎不用逗号）
    assert "断句用换行" in text
    assert "没有，在涂脸" in text


# =====================================================================
# 同类断线（2026-10-16 二轮排查）：规则/调用写了但生产链路不生效
# =====================================================================


def test_aveline_service_exposes_prompt_patch_entry():
    """主动消息改写/压缩依赖 ``AvelineService.execute_prompt_patch``。

    该方法**从未实现过**（``def execute_prompt_patch`` 全历史零命中），两处调用
    的 AttributeError 被自己的 except 吞掉：防复读改写静默降级、超长文本压缩
    失败后由发送门直接 DROP（用户表现为主动消息丢失）。
    """
    import inspect

    from core.services.aveline.service import AvelineService

    assert hasattr(AvelineService, "execute_prompt_patch")
    params = set(inspect.signature(AvelineService.execute_prompt_patch).parameters)
    # 两个调用方用到的关键字参数都必须被接受
    for name in (
        "conversation_id",
        "content",
        "prompt_patch",
        "save_history",
        "model_hint",
        "system_prompt",
    ):
        assert name in params, name


def test_execute_prompt_patch_generates_without_touching_history():
    """默认路径必须是纯生成：带 system 规则、透传 model_path、不落历史。"""
    import asyncio
    from types import SimpleNamespace

    from core.services.aveline.service import AvelineService

    service = AvelineService()
    calls = []

    class _StubLLM:
        async def chat(self, messages, **kwargs):
            calls.append((messages, kwargs))
            return {"response": "压缩后的一句话"}

    service.chat_agent = SimpleNamespace(llm_module=_StubLLM())
    service._chat_agent_init_task = None

    result = asyncio.run(
        service.execute_prompt_patch(
            conversation_id="private_test",
            content="[ACTIVE_CARE_COMPRESS_POKE]",
            prompt_patch="把这条压缩成一句话",
            save_history=False,
            model_hint="cloud:test:model",
            system_prompt="你是消息压缩器。",
        )
    )

    assert result == {"content": "压缩后的一句话"}
    messages, kwargs = calls[0]
    assert messages[0] == {"role": "system", "content": "你是消息压缩器。"}
    assert messages[1] == {"role": "user", "content": "把这条压缩成一句话"}
    assert kwargs.get("model_path") == "cloud:test:model"


def test_study_interaction_policy_injected_only_in_study_mode():
    """``get_natural_dialogue_policy`` 此前零调用；注入器必须真的产出文本。"""
    from core.agents.chat_agent_components.persona_system.prompt import (
        dynamic_injections as di,
    )

    names = [name for name, _ in di.REGISTRY]
    assert "study_interaction_policy" in names

    class _Data:
        def __init__(self, mode: str) -> None:
            self.mode = mode
            self.is_sensitive_mode = False
            self.is_qq_source = False

    def _ctx(mode: str) -> "di.InjectionContext":
        return di.InjectionContext(
            data=_Data(mode),
            agent=None,
            user_id="shared__persona__core_aveline",
            message="讲讲这道题",
            active_tools=None,
        )

    block = di._study_interaction_policy(_ctx("study"))
    assert "学习模式交互规范" in block
    assert block.startswith("<system-reminder>")
    assert "每轮最多做 1 个对话动作" in block

    assert di._study_interaction_policy(_ctx("chat")) == ""
