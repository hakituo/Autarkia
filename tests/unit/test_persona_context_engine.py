"""工作集生命周期、资料完整性与现场仲裁的确定性回归。"""

from datetime import datetime, timedelta, timezone
import json

import pytest

from core.agents.chat_agent_components.persona_system.prompt.context_engine import (
    PersonaWorkingSets, canonical_json, explicit_current_facts, load_chunks, resolve_current_state,
)


@pytest.fixture
def config():
    return {"enabled": True, "max_chunks": 3, "max_tokens": 1200, "max_sessions": 2,
            "session_ttl_seconds": 100, "retention_turns": 3,
            "topic_switch_phrases": ["换个话题"], "scene_ttl_seconds": {"location": 60, "clothing": 120}}


def document(root, name, key, word, value, modes=None):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"id": key, "topic": key, "facts": {"detail": value},
                               "retrieval": {"keywords": [word]},
                               "availability": {"interaction_modes": modes or ["ordinary", "private"]}},
                              ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def chunks(tmp_path):
    document(tmp_path, "school.json", "ye.school", "学校", "学校资料")
    document(tmp_path, "preferences/food.json", "ye.food", "吃什么", "食物资料")
    document(tmp_path, "private.json", "ye.private", "专属主题", "限定模式资料", ["private"])
    return load_chunks(tmp_path)


def test_recursive_registry_versions_and_duplicate_ids(tmp_path):
    p = document(tmp_path, "nested/a.json", "ye.a", "学校", "旧资料")
    first = load_chunks(tmp_path)[0]
    document(tmp_path, "nested/a.json", "ye.a", "学校", "更新后的资料")
    second = load_chunks(tmp_path)[0]
    assert first.id == second.id and first.revision != second.revision
    assert "更新后的资料" in second.payload
    assert p.is_file()
    document(tmp_path, "b.json", "ye.a", "别的", "重复")
    with pytest.raises(ValueError, match="ID 重复"):
        load_chunks(tmp_path)


def test_followup_switch_and_session_isolation(chunks, config):
    store = PersonaWorkingSets()
    def select(text, cid="one", **kw):
        return store.select(chunks, text, conversation_id=cid, now=10, config=config, **kw)[0]
    initial = select("学校")
    assert select("为什么选这个") == initial
    assert select("为什么选这个", "branch") == ()
    assert select("吃什么")[0].id == "ye.food"
    assert select("换个话题") == ()
    assert select("为什么呢") == ()


def test_order_not_scores_and_read_only_probe(chunks, config):
    store = PersonaWorkingSets()
    first, _ = store.select(chunks, "学校 吃什么", conversation_id="one", now=10, config=config)
    second, _ = store.select(chunks, "学校学校", conversation_id="one", now=11, config=config)
    assert [c.id for c in first] == [c.id for c in second]
    previous = store._sessions[("default", "one")]
    store.select(chunks, "吃什么", conversation_id="one", now=12, config=config, update=False)
    assert store._sessions[("default", "one")] == previous


def test_ttl_retention_capacity_and_reset(chunks, config):
    store = PersonaWorkingSets()
    def select(text, cid="a", now=10):
        return store.select(chunks, text, conversation_id=cid, now=now, config=config)[0]
    select("学校")
    for msg in ("为什么", "原来如此", "明白了", "好"):
        last = select(msg)
    assert last == ()
    select("学校")
    assert select("那呢", now=111) == ()
    select("学校", "b")
    select("学校", "c")
    assert len(store._sessions) == 2
    store.clear("b")
    assert all(k[1] != "b" for k in store._sessions)


def test_mode_revocation_and_namespace_isolation(chunks, config):
    store = PersonaWorkingSets()
    private, _ = store.select(chunks, "专属主题", conversation_id="a", mode="private", now=1, config=config)
    assert private
    ordinary, _ = store.select(chunks, "继续", conversation_id="a", mode="ordinary", now=2, config=config)
    assert ordinary == ()
    store.select(chunks, "学校", conversation_id="a", namespace="root1", now=2, config=config)
    result, _ = store.select(chunks, "继续", conversation_id="a", namespace="root2", now=2, config=config)
    assert result == ()


def test_budget_is_bounded_and_stateless_has_no_leak(chunks, config):
    store = PersonaWorkingSets()
    cfg = {**config, "max_tokens": 1}
    result, trace = store.select(chunks, "学校吃什么", now=1, config=cfg)
    assert result == () and trace["estimated_tokens"] == 0
    store.select(chunks, "学校", now=2, config=config)
    assert store.select(chunks, "为什么", now=3, config=config)[0] == ()
    assert not store._sessions


def test_canonical_render_is_not_json_key_order():
    assert canonical_json({"z": 2, "a": 1}) == canonical_json({"a": 1, "z": 2})


def test_expired_recent_and_invalid_runtime_are_not_current(config):
    now = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    stale = {"value": "旧地点", "source": "user_explicit",
             "updated_at": (now - timedelta(seconds=61)).isoformat()}
    assert resolve_current_state({}, recent_facts={"location": stale}, now=now, config=config) == {}
    # 无法判断新鲜度的时间戳（缺失/非法/未来）保留原值，但不算 stale：
    # 丢掉会让模型对这段状态一无所知，只能重新编一个值。
    for stamp in (None, "invalid", (now + timedelta(seconds=1)).isoformat()):
        kept = resolve_current_state({"location": {**stale, "updated_at": stamp}}, now=now, config=config)
        assert kept["location"]["value"] == "旧地点"
        assert not kept["location"].get("stale")


def test_actual_nested_food_registry_handles_everyday_question():
    from core.agents.chat_agent_components.persona_system.prompt.context_engine import rank_chunks
    from core.utils.common import get_project_root
    catalog = load_chunks(get_project_root() / "core/character/configs/ye/knowledge")
    selected = rank_chunks(catalog, "累了一天又懒得挑吃的，你会买什么", "ordinary")
    assert selected[0].id == "ye.preference.food_and_drink"


def test_prefix_composition_keeps_history_and_static_independent():
    from core.agents.chat_agent_components.persona_system.prompt.assembler import build_persona_message_prefix
    history = [{"role": "user", "content": "上一轮问题"}, {"role": "assistant", "content": "实际回答"}]
    first = build_persona_message_prefix("固定规则", "资料甲", history)
    second = build_persona_message_prefix("固定规则", "资料乙", history)
    assert first[0] == second[0] == {"role": "system", "content": "固定规则"}
    assert first[1] == {"role": "user", "content": "资料甲"}
    assert first[2:] == second[2:] == history


def test_fresh_fact_beats_old_state_expiry_and_rejected_sources(config):
    now = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    old = {"value": "旧地点", "updated_at": (now - timedelta(seconds=30)).isoformat(), "source": "llm_tool"}
    fresh = {"value": "新地点", "updated_at": now.isoformat(), "source": "user_explicit"}
    assert resolve_current_state({"location": old}, recent_facts={"location": fresh}, now=now, config=config)["location"] == fresh
    untrusted = {**fresh, "source": "retrieved_memory"}
    assert resolve_current_state({"location": old}, recent_facts={"location": untrusted}, now=now, config=config)["location"] == old
    # 超过 TTL 但在硬上限（TTL×4）内：保留最后已知值并标记 stale
    stale_state = resolve_current_state({"location": old}, now=now + timedelta(seconds=31), config=config)
    assert stale_state["location"]["value"] == "旧地点"
    assert stale_state["location"]["stale"] is True
    assert stale_state["location"]["stale_seconds"] == 61
    # 超过硬上限：彻底丢弃，避免很久以前的现场被当成仍然成立的事实
    assert "location" not in resolve_current_state(
        {"location": old}, now=now + timedelta(seconds=241), config=config
    )
    cleared = {**fresh, "value": None}
    assert resolve_current_state({"location": old}, recent_facts={"location": cleared}, now=now, config=config)["location"]["value"] is None


def test_current_user_correction_not_user_location():
    now = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    assert explicit_current_facts("我现在在宿舍", now) == {}
    assert explicit_current_facts("你现在在宿舍吗？", now) == {}
    assert explicit_current_facts("你现在在宿舍", now)["location"]["value"] == "宿舍"


def test_maintenance_evidence_fields_never_reach_static_prompt(tmp_path):
    """authoring_notes / evidence_refs / source 是人工复核材料，不进 Prompt。

    2026-10-19 TT 实测：这些字段一度把原始聊天记录文件名和行号索引带进 system
    prompt，其中 authoring_notes 单独占了 45% 的静态前缀。
    """
    from core.agents.chat_agent_components.persona_system.prompt.layered_context import (
        build_layered_persona_context, clear_persona_context_cache,
    )

    (tmp_path / "core_fixture.json").write_text(
        json.dumps(
            {
                "authoring_notes": {"evidence": [{"file": "raw_chat.txt", "line": 12}]},
                "identity": {"name": "fixture"},
                "personality_core": [
                    {
                        "id": "direct",
                        "behavior": "直接回一句，不解释",
                        "confidence": "medium",
                        "evidence_refs": ["E03"],
                        "source": "raw_chat.txt 2026-09",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "voice_fixture.json").write_text(
        json.dumps(
            {
                "tone": {"summary": "短句为主", "evidence": "raw_chat.txt 全天样本"},
                "authoring_notes": "维护索引",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    clear_persona_context_cache()
    try:
        layers = build_layered_persona_context(
            profile_filename="fixture.json",
            root=tmp_path,
            memory_root=tmp_path / "memory",
            runtime_state={},
            message="今天天气怎么样",
            persona_data={
                "meta": {
                    "scope": "fixture",
                    "context_profile": {
                        "core": "core_fixture.json",
                        "voice": "voice_fixture.json",
                    },
                }
            },
        )
    finally:
        clear_persona_context_cache()

    assert layers is not None
    assert "[CHARACTER CORE]" in layers.static_prompt
    assert "[CHARACTER VOICE]" in layers.static_prompt
    assert "直接回一句" in layers.static_prompt
    assert "短句为主" in layers.static_prompt
    for leaked in ("authoring_notes", "evidence_refs", "raw_chat.txt", "confidence"):
        assert leaked not in layers.static_prompt


def test_two_inline_personas_share_engine_without_extra_files(tmp_path):
    from core.agents.chat_agent_components.persona_system.prompt.layered_context import (
        build_layered_persona_context, clear_persona_context_cache,
    )
    clear_persona_context_cache()
    now = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)

    def build(scope, message, value, runtime=None):
        return build_layered_persona_context(
            profile_filename=f"{scope}.json", conversation_id="same-branch", now=now,
            root=tmp_path, memory_root=tmp_path / "memory", runtime_state=runtime or {},
            message=message, persona_data={"meta": {"scope": scope, "context_profile": {
                "core": {"identity": {"real_name": scope}}, "voice": {"reply": "简短自然"},
                "relationship": {"baseline": "朋友"},
                "knowledge": [{"id": "school", "topic": "学校", "facts": {"name": value},
                               "retrieval": {"keywords": ["学校"]}}],
            }}},
        )

    try:
        first = build("fixture_a", "学校", "甲校")
        other = build("fixture_b", "为什么呢", "乙校")
        followup = build("fixture_a", "为什么呢", "甲校", {"state": {"location": "宿舍"}})
        assert other.working_set_prompt == ""
        assert first.working_set_prompt == followup.working_set_prompt
        assert first.static_prompt == followup.static_prompt
        assert "甲校" not in first.static_prompt and "宿舍" not in first.static_prompt
        assert "宿舍" in followup.dynamic_prompt
        revised = build("fixture_a", "接着说", "甲校新资料")
        assert revised.working_set_prompt != first.working_set_prompt
        assert revised.static_prompt == first.static_prompt
        assert not list(tmp_path.rglob("*.json"))
    finally:
        clear_persona_context_cache()
