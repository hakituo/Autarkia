"""pytest 共享沙箱 fixture（按需使用，不自动生效）。

由 ``tests/conftest.py`` 显式导入注册；拆成独立模块是为了让 conftest 保持在 300 行以内。
"""

from __future__ import annotations

import pytest


def _reset_singletons() -> None:
    """重置学习系统全部单例，避免跨用例复用上一个沙箱的路径与内存状态。"""
    from core.services.study import (
        concept_state,
        daily_tracker,
        learning_event,
        resources,
        student_state,
        study_library,
        subject_registry,
        teaching_orchestrator,
        weakness_tracker,
    )

    concept_state.ConceptStateManager._instance = None
    learning_event.LearningEventStore._instance = None
    resources.ResourceRegistry._instance = None
    weakness_tracker.WeaknessTracker._instance = None
    student_state.StudentStateManager._instance = None
    teaching_orchestrator.TeachingOrchestrator._instance = None
    subject_registry._registry = None
    study_library.StudyLibraryIndex._instance = None

    # 每日总结调度入口的进程内补写状态（按日期去重）
    from core.services.journal import daily_summary_dispatch

    daily_summary_dispatch.reset_backfill_state()

    dt = daily_tracker.DailyTracker
    if dt._instance is not None:
        dt._instance._cache.clear()
    dt._instance = None


@pytest.fixture()
def study_sandbox(tmp_path, monkeypatch):
    """把学习系统状态根目录指向临时目录，并重置相关单例。"""
    from core.services.study import paths

    root = tmp_path / "study"
    (root / ".state").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "get_study_root", lambda: root)

    _reset_singletons()
    yield root
    _reset_singletons()


@pytest.fixture()
def agenda_sandbox(tmp_path, monkeypatch):
    """把议程状态文件（走 get_user_data_dir）隔离到临时目录。

    议程注入会把「今天已注入过哪些 / 连续闲聊了几轮」写进
    ``daily/<y>/<m>/<d>/agenda_injected.json``。不隔离就会往真实
    ``companion_data`` 里塞测试会话 —— 2026-10-02 实测被写过 ``u1`` 与
    ``shared__persona__test`` 两条。

    刻意**不 autouse**：只有需要它的用例才隔离，避免影响那些依赖真实用户数据的用例。
    需要「本文件所有用例都隔离」时，在文件里加一个 autouse fixture 依赖它。
    """
    import core.utils.data_paths as data_paths

    monkeypatch.setattr(data_paths, "get_user_data_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture()
def fake_agenda_ladder(monkeypatch):
    """把议程优先级阶梯换成可控假探针，并记录调用与提交。

    once_per_day / chitchat_gated 统一给 False —— 优先级行为、每天一次节流、
    闲聊门控三者分开测，混在一起失败时说不清是谁的锅。
    """
    from core.agents.chat_agent_components.streaming_pipeline import (
        agenda_injections as ai,
    )

    def build(*, hits: dict[str, str]):
        calls: list[str] = []
        commits: list[str] = []

        def make(name: str):
            async def probe(ctx):
                calls.append(name)
                text = hits.get(name, "")
                if not text:
                    return "", None

                async def commit():
                    commits.append(name)

                return text, commit

            return probe

        ladder = tuple(ai.AgendaItem(name, make(name), False, False) for name in ai.AGENDA_PRIORITY)
        monkeypatch.setattr(ai, "_LADDER", ladder)
        return calls, commits

    return build
