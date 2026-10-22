from __future__ import annotations

from pathlib import Path

from core.character.managers.persona_manager import PersonaManager


PROJECT_ROOT = Path(__file__).resolve().parents[2]

def _make_manager() -> PersonaManager:
    manager = object.__new__(PersonaManager)
    manager.configs_dir = str(PROJECT_ROOT / "core/character/configs")
    manager.current_persona_file = "core_ling.json"
    manager.current_persona_data = {}
    manager.model_persona_map = {}
    manager._revision = 0
    return manager


def test_ling_default_entry_is_layered_v2_and_v1_stays_selectable() -> None:
    manager = _make_manager()
    personas = manager.list_personas()
    by_filename = {str(item.get("filename") or ""): item for item in personas}

    # 2026-10-02 app.yaml persona.default_map 刻意把 ling 默认改指 sensitive 变体入口：
    # 安卓 role 级会话（web_role_ling）不携带 persona，只能落到这张表。QQ 端在
    # multi_qq_config.json 里显式配了 core_ling.json，账号配置优先于本表、不受影响。
    default_entry = by_filename["variants/ling_b.json"]
    base = by_filename["core_ling.json"]
    legacy = by_filename["core_ling_v1.json"]

    # 默认入口是分层 V2 选择器（scope=ling，只叠加 love 变体层），V2 base 与 V1 均为可选非默认。
    assert default_entry["name"] == "Ling"
    assert legacy["name"] == "Ling（V1）"
    assert default_entry["role"] == legacy["role"] == "Ling"
    assert base["role"] == "Ling"
    assert default_entry["is_default"] is True
    assert base["is_default"] is False
    assert legacy["is_default"] is False
    # 默认人设排在该角色第一位；V1 保持可选但排在默认之后。
    assert personas.index(default_entry) < personas.index(base)
    assert personas.index(default_entry) < personas.index(legacy)

    # core_ling.json 仍是分层 V2 base：客户端显式选择它时口径不变（V1 之上的稳定入口）。
    loaded = manager.get_persona_by_filename("core_ling.json")
    assert loaded["meta"]["scope"] == "ling"
    profile = loaded["meta"]["context_profile"]
    assert profile["enabled"] is True
    assert profile["root"] == "ling"
    assert profile["voice"] == "voice_ling.json"
    assert profile["relationship"] == "relationship_ling.json"
    assert profile["temporal_profile"] == "temporal_profile.json"
    assert "selected_overlay" not in profile

    # V1 保留为可选回退版本，但它是最初的扁平人设，不声明分层上下文。
    legacy_loaded = manager.get_persona_by_filename("core_ling_v1.json")
    assert "context_profile" not in (legacy_loaded.get("meta") or {})
    assert legacy_loaded["identity"]["name"] == "Ling（V1）"


def test_ling_b_inherits_v2_and_adds_only_selected_variant() -> None:
    manager = _make_manager()
    love = manager.get_persona_by_filename("variants/ling_b.json")

    assert love["meta"]["scope"] == "ling"
    profile = love["meta"]["context_profile"]
    assert profile["enabled"] is True
    assert profile["root"] == "ling"
    assert profile["core"] == "core_ling.json"
    assert profile["voice"] == "voice_ling.json"
    assert profile["relationship"] == "relationship_ling.json"
    assert profile["temporal_profile"] == "temporal_profile.json"
    assert profile["knowledge"] == "knowledge"
    assert profile["selected_overlay"] == "overlays/b_ling.json"

    # Love 仍是一个显式可选敏感 persona，工具权限由子层拥有；V2 base 不需要知道它。
    assert {"scene", "sensitive_meme"} <= set(
        love.get("tool_access", {}).get("allow_categories") or []
    )
