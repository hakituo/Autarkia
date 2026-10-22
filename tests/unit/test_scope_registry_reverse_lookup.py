"""``scope → persona 入口文件名`` 反查接口单元测试。

覆盖目标：``core/utils/data/scope_registry.py::resolve_profile_filename_from_scope``

背景：正向的 ``resolve_persona_slug_scope``（别名 → scope）回答不了「这个 scope 是
哪个角色」。主动关怀分发在单角色模式下只有 scope、拿不到 profile_filename，payload
缺少归属字段，客户端就会「有通知、点进去却没有这条消息」。

约定：
- persona 配置目录统一指向 pytest 的 ``tmp_path``，绝不读真实 ``core/character/configs``；
  只有最后一个用例刻意读真实目录，用来钉住线上规范入口不被改动。
- 注册表是模块级全局状态，fixture 在用例结束后恢复真实注册表，避免跨用例污染。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.utils.data import scope_registry


def _write_persona(path: Path, scope: str, name: str, *, deprecated: bool = False) -> None:
    """写一个能被注册表扫描到的最小 persona 配置。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"scope": scope}
    if deprecated:
        meta["deprecated"] = True
    path.write_text(
        json.dumps({"identity": {"name": name}, "meta": meta}, ensure_ascii=False),
        encoding="utf-8",
    )


@pytest.fixture
def sandbox(tmp_path):
    """把注册表指向临时 persona 目录，用例结束后恢复真实注册表。"""
    configs = tmp_path / "configs"
    configs.mkdir()

    def refresh() -> None:
        scope_registry.refresh_scope_registry(configs)

    refresh()
    yield configs, refresh
    scope_registry.refresh_scope_registry()


# ==================== 规范入口的选择 ====================


def test_prefers_top_level_entry(sandbox):
    """顶层 ``core_<scope>.json`` 优先于分层目录里的同名入口。"""
    configs, refresh = sandbox
    _write_persona(configs / "core_aveline.json", "aveline", "Aveline")
    _write_persona(configs / "aveline" / "core_aveline.json", "aveline", "Aveline")
    refresh()

    assert scope_registry.resolve_profile_filename_from_scope("aveline") == "core_aveline.json"


def test_uses_layered_entry_without_top_level(sandbox):
    """没有顶层入口时，退到分层目录 ``<scope>/core_<scope>.json``。"""
    configs, refresh = sandbox
    _write_persona(configs / "lin" / "core_lin.json", "lin", "林知夏")
    refresh()

    assert scope_registry.resolve_profile_filename_from_scope("lin") == "lin/core_lin.json"


def test_ignores_variant_files(sandbox):
    """同 scope 的变体文件（学习 / 敏感向）不能抢走规范入口。"""
    configs, refresh = sandbox
    _write_persona(configs / "aveline" / "core_aveline.json", "aveline", "Aveline")
    _write_persona(configs / "study" / "Aveline_Study.json", "aveline", "Aveline")
    _write_persona(configs / "sensitive" / "Aveline_love.json", "aveline", "Aveline")
    refresh()

    assert scope_registry.resolve_profile_filename_from_scope("aveline") == (
        "aveline/core_aveline.json"
    )


def test_scan_order_does_not_change_result(sandbox):
    """规范入口由优先级决定，不随文件系统扫描顺序漂移。"""
    configs, refresh = sandbox
    # 先写变体、后写规范入口，与上一条顺序相反，结果必须一致。
    _write_persona(configs / "study" / "Aveline_Study.json", "aveline", "Aveline")
    _write_persona(configs / "aveline" / "core_aveline.json", "aveline", "Aveline")
    refresh()

    assert scope_registry.resolve_profile_filename_from_scope("aveline") == (
        "aveline/core_aveline.json"
    )


def test_case_insensitive_and_preserves_real_case(sandbox):
    """scope 查询大小写不敏感，返回值保留磁盘上的真实大小写。"""
    configs, refresh = sandbox
    _write_persona(configs / "TT" / "core_TT.json", "TT", "TT")
    refresh()

    assert scope_registry.resolve_profile_filename_from_scope("tt") == "TT/core_TT.json"
    assert scope_registry.resolve_profile_filename_from_scope("TT") == "TT/core_TT.json"


def test_deprecated_persona_is_not_registered(sandbox):
    """已废弃的人设不参与反查。"""
    configs, refresh = sandbox
    _write_persona(configs / "core_dead.json", "dead", "Dead", deprecated=True)
    refresh()

    assert scope_registry.resolve_profile_filename_from_scope("dead") == ""


# ==================== 必须拒绝的情形 ====================


@pytest.mark.parametrize("scope", ["user", "dual_role"])
def test_special_scopes_return_empty(sandbox, scope):
    """``user`` / ``dual_role`` 不是角色，不能反查出人设文件。"""
    assert scope_registry.resolve_profile_filename_from_scope(scope) == ""


@pytest.mark.parametrize("scope", ["", "   ", None, "nope", "unknown_role"])
def test_unknown_or_blank_scope_returns_empty(sandbox, scope):
    """查不到就返回空串，绝不凭 scope 名臆造路径。"""
    assert scope_registry.resolve_profile_filename_from_scope(scope) == ""


def test_isolated_scope_returns_empty(sandbox):
    """隔离 scope（``persona_<hash>``）必须反查失败，否则无主会话会被塞进真实角色。"""
    scope = scope_registry.resolve_data_scope_from_conversation_id("web_role_deadbeef")
    assert scope.startswith("persona_")

    assert scope_registry.resolve_profile_filename_from_scope(scope) == ""


# ==================== 往返一致性 ====================


def test_round_trip_collapses_variants_to_canonical_entry(sandbox):
    """文件名 → scope → 文件名 必须收敛到唯一规范入口。"""
    configs, refresh = sandbox
    _write_persona(configs / "core_ling.json", "ling", "Ling")
    _write_persona(configs / "ling" / "core_ling.json", "ling", "Ling")
    _write_persona(configs / "sensitive" / "Ling_b.json", "ling", "Ling")
    refresh()

    for filename in ("core_ling.json", "ling/core_ling.json", "variants/ling_b.json"):
        resolved_scope = scope_registry.resolve_persona_slug_scope(filename)
        assert resolved_scope == "ling"
        assert scope_registry.resolve_profile_filename_from_scope(resolved_scope) == (
            "core_ling.json"
        )


# ==================== 真实配置回归钉 ====================


def test_real_configs_resolve_canonical_entries():
    """真实 persona 目录的规范入口：改动角色配置布局时这里会先报错。"""
    scope_registry.refresh_scope_registry()
    try:
        assert scope_registry.resolve_profile_filename_from_scope("aveline") == (
            "core_aveline.json"
        )
        assert scope_registry.resolve_profile_filename_from_scope("ling") == "core_ling.json"
    finally:
        scope_registry.refresh_scope_registry()
