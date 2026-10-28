"""生产按段提取器（v3 F3，C8 结论的 B 形态：每段一条梗概）。假调度器，不调用模型。"""

from __future__ import annotations

import asyncio
import json
import threading

import pytest

from memory.nightly.segment_jobs import extractors
from memory.nightly.segment_jobs import run as seg_run
from memory.nightly.segment_jobs.episode import (
    EPISODE_EXTRACTOR_VERSION,
    EpisodeExtractor,
    EpisodeParseError,
    parse_episode,
)
from memory.nightly.segment_jobs.inputs import SegmentParams, build_conversation_inputs
from memory.nightly.segment_jobs.prompts import TASK_INSTRUCTION, build_messages
from memory.notes import NoteStore, paths

CONV = "web_role_aveline"
NIGHT = 10_000_000.0
PERSPECTIVE = {"role_id": "aveline", "role_name": "Aveline", "user_name": "Master", "role_profile": ""}
PERSONA_PREFIX = "你是Aveline。你性格安静，嘴上不饶人但心软，说话简短。\n和你说话的人是Master。"
SENSITIVE = {
    "error": "x",
    "non_retryable": True,
    "details": {"status": 422, "body": "input new_sensitive (1026)"},
}


class _Scheduler:
    """按顺序吐出预设的流式 chunk 列表，并记下每次调用的参数。"""

    def __init__(self, *plans):
        self.plans = list(plans)
        self.calls = []

    async def submit_llm_task(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        for chunk in self.plans.pop(0):
            yield chunk


def _msg(eid, role, content, ts, turn):
    return {
        "event_id": eid,
        "conversation_id": CONV,
        "role": role,
        "content": content,
        "timestamp": ts,
        "event_type": "chat_message",
        "message_id": turn,
    }


def _segments(turns=2):
    events = []
    for index in range(turns):
        ts = 1000.0 + index * 60
        events.append(_msg(f"e-u{index}", "user", f"我换成乌龙茶了{index}", ts, f"m{index}"))
        events.append(_msg(f"e-a{index}", "assistant", f"好，记住了{index}", ts + 1, f"m{index}"))
    return build_conversation_inputs(
        "aveline",
        CONV,
        events,
        params=SegmentParams(max_turns=8),
        now=NIGHT,
        tree_reader=lambda _cid: events,
    )


def _extractor(
    scheduler,
    model_hint="cloud:minimax:plan:MiniMax-M3",
    *,
    persona_prefix=PERSONA_PREFIX,
    fallback_for_scope=None,
):
    return EpisodeExtractor(
        scheduler_provider=lambda: scheduler,
        model_hint=model_hint,
        perspective_for_scope=lambda _scope: PERSPECTIVE,
        persona_prefix_for_scope=lambda _scope: persona_prefix,
        fallback_for_scope=fallback_for_scope,
    )


def _reply(summary="", skip=""):
    return [json.dumps({"summary": summary, "skip": skip}, ensure_ascii=False)]


def test_parse_episode_accepts_summary_skip_and_code_fence():
    assert parse_episode('{"summary": "聊了换茶", "skip": ""}') == ("聊了换茶", "")
    assert parse_episode('```json\n{"summary": "", "skip": "no_reusable_info"}\n```') == (
        "",
        "no_reusable_info",
    )
    for bad in ("没有 JSON", '{"summary": "", "skip": ""}', "[1, 2]"):
        with pytest.raises(EpisodeParseError):
            parse_episode(bad)


def test_extract_writes_one_episode_sourced_from_whole_segment():
    item = _segments()[0]
    scheduler = _Scheduler(_reply(summary="Master说换成乌龙茶了，我记下了。"))
    result = asyncio.run(_extractor(scheduler).extract(item))

    assert result.extractor_version == EPISODE_EXTRACTOR_VERSION and not result.skip_reason
    (note,) = result.notes
    assert note.kind == "episode" and "乌龙茶" in note.text
    assert set(note.source_event_ids) == {"e-u0", "e-a0", "e-u1", "e-a1"}
    call = scheduler.calls[0]
    # 推理模型思考 token 计入 max_tokens：预算至少 4096；用的是蒸馏模型、角色第一人称视角
    assert call["max_tokens"] >= 4096 and call["model_hint"].endswith("MiniMax-M3")
    system, user = call["prompt"][0]["content"], call["prompt"][1]["content"]
    # system = 角色静态人设前缀 + 固定提取指令；对话只在末尾 user 消息里
    assert system.startswith(PERSONA_PREFIX) and TASK_INSTRUCTION in system
    assert "这次你是" not in user
    assert "这是你和Master的一段真实聊天记录" in user
    assert "【说话者】Master\n我换成乌龙茶了0" in user


def test_persona_prefix_is_role_specific_and_repeatable():
    first = build_messages([{"role": "user", "content": "在吗"}], PERSPECTIVE, persona_prefix="甲人设")
    same = build_messages([{"role": "user", "content": "早"}], PERSPECTIVE, persona_prefix="甲人设")
    other = build_messages(
        [{"role": "user", "content": "早"}],
        {"role_id": "ye", "role_name": "Ye", "user_name": "主人", "role_profile": ""},
        persona_prefix="乙人设",
    )
    neutral = build_messages([{"role": "user", "content": "早"}], {})
    assert first[0] == same[0] and first[0] != other[0]
    assert first[0]["content"].startswith("甲人设") and other[0]["content"].startswith("乙人设")
    # 认不出角色时仍能给出中性身份，不会把别人的名字写进 system
    assert neutral[0]["content"].startswith("你是助手。")


def test_offline_role_prefix_is_long_stable_and_role_specific():
    from core.agents.chat_agent_components.persona_system.prompt.offline_persona_prefix import (
        build_offline_role_prefix,
        clear_offline_role_prefix_cache,
    )

    clear_offline_role_prefix_cache()
    first = build_offline_role_prefix("aveline")
    same = build_offline_role_prefix("aveline")
    other = build_offline_role_prefix("ling")
    assert len(first) >= 3000 and first == same and first != other
    assert "Aveline" in first and "Ling" in other
    assert build_offline_role_prefix("not_a_role") == ""


def test_offline_role_prefix_does_not_cache_transient_failures(monkeypatch):
    from core.agents.chat_agent_components.persona_system.prompt import (
        offline_persona_prefix as module,
    )

    module.clear_offline_role_prefix_cache()
    attempts = {"count": 0}

    def flaky(scope: str, user_name: str) -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("transient read failure")
        return "恢复后的前缀"

    monkeypatch.setattr(module, "_build", flaky)
    assert module.build_offline_role_prefix("aveline") == ""
    assert module.build_offline_role_prefix("aveline") == "恢复后的前缀"
    module.clear_offline_role_prefix_cache()


def test_extract_reports_skip_when_model_says_nothing_reusable():
    item = _segments()[0]
    result = asyncio.run(_extractor(_Scheduler(_reply(skip="no_reusable_info"))).extract(item))
    assert result.notes == () and result.skip_reason == "no_reusable_info"


def test_extract_raises_on_empty_response_so_job_is_retried():
    item = _segments()[0]
    scheduler = _Scheduler([""], [""], [""])  # 支持思考开关的路由会重试 3 次，仍空才抛
    with pytest.raises(EpisodeParseError):
        asyncio.run(_extractor(scheduler).extract(item))
    assert 1 <= len(scheduler.calls) <= 3


def test_sensitive_rejection_switches_to_role_fallback_model():
    item = _segments()[0]
    scheduler = _Scheduler([SENSITIVE], _reply(summary="改用降级型号写的梗概"))
    extractor = _extractor(
        scheduler,
        fallback_for_scope=lambda _scope: "cloud:deepseek:aveline:deepseek-v4-flash",
    )
    result = asyncio.run(extractor.extract(item))

    assert result.notes[0].text == "改用降级型号写的梗概"
    assert scheduler.calls[1]["model_hint"] == "cloud:deepseek:aveline:deepseek-v4-flash"


def test_ensure_default_factory_does_not_override_registered():
    sentinel = object()
    extractors.register_extractor_factory(lambda _config: sentinel)
    extractors.ensure_default_factory()
    assert extractors.resolve_extractor({}) is sentinel

    extractors.reset_extractor_registry()
    extractors.ensure_default_factory()
    assert extractors._factory is not None


class _Manager:
    def __init__(self, history_dir):
        self.user_id = "shared__scope__aveline"
        self.storage_scope = "aveline"
        self._memory_layout = {"history_dir": str(history_dir)}
        self.lock = threading.RLock()


def test_run_segment_jobs_end_to_end_writes_note_store(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "notes_dir", lambda scope: tmp_path / "notes" / scope)
    monkeypatch.setattr(seg_run, "resolve_distillation_perspective", lambda _m: PERSPECTIVE)
    manager, store = _Manager(tmp_path / "memories"), NoteStore("aveline")
    config = {
        "segment_extraction_enabled": True,
        "distillation_role_whitelist": ["aveline"],
        "segment_max_per_night": 0,
        "segment_max_chars_per_night": 0,
        "segment_max_seconds_per_night": 0,
    }
    scheduler = _Scheduler(_reply(summary="Master换成了乌龙茶。"))

    def run():
        return asyncio.run(
            seg_run.run_segment_jobs(
                manager.user_id,
                manager,
                config,
                extractor=_extractor(scheduler),
                note_store=store,
                segments=_segments(),
                now=NIGHT,
            )
        )

    first = run()
    notes = store.list_notes(CONV)
    assert first["done"] == 1 and len(notes) == 1
    assert (
        notes[0]["kind"] == "episode" and notes[0]["extractor_version"] == EPISODE_EXTRACTOR_VERSION
    )
    # 第二晚：同版本已完成，不再调用模型
    second = run()
    assert second["done"] == 0 and len(scheduler.calls) == 1


@pytest.mark.parametrize("old_version", ["segment-episode-3", "segment-episode-4"])
def test_accepted_old_notes_count_as_done_and_are_not_rerun(
    tmp_path, monkeypatch, old_version
):
    """写法升到 v5 后，已回填的 v3 / v4 梗概都不重跑（用户决定不为改写法重花钱）。"""
    monkeypatch.setattr(paths, "notes_dir", lambda scope: tmp_path / "notes" / scope)
    monkeypatch.setattr(seg_run, "resolve_distillation_perspective", lambda _m: PERSPECTIVE)
    manager, store = _Manager(tmp_path / "memories"), NoteStore("aveline")
    (item,) = _segments()
    store.replace_segment(
        CONV,
        item.segment_id,
        old_version,
        [{"kind": "episode", "text": "旧版梗概。", "source_event_ids": ("e-u0",)}],
        segment_source_event_ids=item.segment.source_event_ids,
    )
    scheduler = _Scheduler(_reply(summary="不该被调用"))
    config = {
        "segment_extraction_enabled": True,
        "distillation_role_whitelist": ["aveline"],
        "segment_max_per_night": 0,
        "segment_max_chars_per_night": 0,
        "segment_max_seconds_per_night": 0,
    }
    report = asyncio.run(
        seg_run.run_segment_jobs(
            manager.user_id,
            manager,
            config,
            extractor=_extractor(scheduler),
            note_store=store,
            segments=[item],
            now=NIGHT,
        )
    )
    assert scheduler.calls == [] and report.get("done", 0) == 0
    assert [n["text"] for n in store.list_notes(CONV)] == ["旧版梗概。"]
