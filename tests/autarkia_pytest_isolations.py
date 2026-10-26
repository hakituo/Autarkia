"""pytest 全局隔离 fixture（按用例自动重置进程内状态）。

由 ``tests/conftest.py`` 显式导入注册；拆成独立模块是为了让 conftest 保持在 300 行以内。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_current_channel():
    """还原「当前渠道」ContextVar。

    ``ChatAgent.stream_chat`` 会按 platform 设置它；pytest 用例共用同一个 context，
    不还原就会把上一个用例的渠道带进下一个（表现为历史消息凭空多出「（来自QQ）」）。
    """
    from core.utils.data.chat_channel import reset_current_platform, set_current_platform

    token = set_current_platform("")
    yield
    reset_current_platform(token)


@pytest.fixture(autouse=True)
def _reset_topology_tree_registry(monkeypatch, tmp_path_factory):
    """丢弃进程内常驻消息树单例，并关掉本机拓扑覆盖层，避免读到真实回填文件。"""
    from memory.topology import tree_registry

    from memory.topology import cursors

    monkeypatch.setattr(tree_registry, "_default_overlay_loader", lambda _cid, _scope: None)
    # 分支游标落到临时目录，并关掉覆盖层 active_leaf 兜底：写入路径的用例不得写真实数据
    cursor_root = tmp_path_factory.mktemp("cursors")
    monkeypatch.setattr(cursors, "base_dir_for", lambda scope: cursor_root / scope)
    monkeypatch.setattr(cursors, "load_overlay", lambda _cid, _scope: None)
    cursors.reset_cursor_cache()
    tree_registry.reset_tree_registry()
    yield
    tree_registry.reset_tree_registry()
    cursors.reset_cursor_cache()


@pytest.fixture(autouse=True)
def _reset_segment_extractor_registry():
    """按段提取器注册点是进程内全局，用例之间不得互相继承注册的提取器。"""
    from memory.nightly.segment_jobs import extractors

    extractors.reset_extractor_registry()
    yield
    extractors.reset_extractor_registry()


@pytest.fixture(autouse=True)
def _reset_offline_role_prefix_cache():
    """离线人设前缀是进程内缓存，用例之间不得复用别的人设或 monkeypatch 结果。"""
    from core.agents.chat_agent_components.persona_system.prompt.offline_persona_prefix import (
        clear_offline_role_prefix_cache,
    )

    clear_offline_role_prefix_cache()
    yield
    clear_offline_role_prefix_cache()


@pytest.fixture(autouse=True)
def _reset_note_retrieval_cache(monkeypatch, tmp_path_factory):
    """笔记库指到临时目录（search_memory 默认会读梗概，不得读到真实回填的笔记），
    并清掉按 scope 缓存的语料与 BM25，用例之间不得复用别的用例造的笔记。"""
    from memory.notes import paths
    from memory.notes.retrieval import reset_note_retrieval_cache

    notes_root = tmp_path_factory.mktemp("notes")
    monkeypatch.setattr(paths, "notes_dir", lambda scope: notes_root / scope)
    reset_note_retrieval_cache()
    yield
    reset_note_retrieval_cache()


@pytest.fixture(autouse=True)
def _daily_submodules_follow_facade_clock(monkeypatch):
    """让 daily 子模块的时间函数跟随**门面**上被 patch 的值。

    2026-10-02 把 `core/services/daily/manager.py`（862 行）拆成薄壳门面 + 4 个
    mixin 子模块后，`now_str` / `today_str` / `get_current_time` 各自被搬进真正用它的
    子模块。测试历来只 patch 门面（`monkeypatch.setattr(manager_mod, "now_str", ...)`），
    不跟随就会让子模块继续用真实时间 —— 实测 `record_study` 记到 15:58 而不是固定的 12:00。

    这里给每个子模块装一个「转发到门面」的代理：门面仍是唯一的时间开关，
    既不用改各处 patch，也不会让子模块与门面各冻结一份、慢慢漂移。
    """
    from core.services.daily import daily_entries, daily_record_store, daily_sleep, daily_summary
    from core.services.daily import manager as facade

    for mod in (daily_record_store, daily_sleep, daily_entries, daily_summary):
        for name in ("now_str", "today_str", "get_current_time"):
            if hasattr(mod, name):
                # 默认参数把 name 绑死；getattr 在调用时才解析，才能取到后来 patch 的值
                monkeypatch.setattr(
                    mod,
                    name,
                    (lambda n=name: lambda *a, **k: getattr(facade, n)(*a, **k))(),
                )
    yield
