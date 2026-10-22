"""数据路径迁移逻辑 —— 兼容门面（唯一实现在 ``data_paths``）。

历史遗留：本模块曾与 ``data_paths.py`` 各存一份迁移实现，两份已经**漂移**
（``data_paths.py`` 侧更新：动态角色 scope 走注册表、裸 ``ling`` 文件归位分支），
哪天有调用切到旧副本就是数据布局损坏。现在统一为：

- **唯一实现**：``core.utils.data.data_paths``（本模块按原名再导出）；
- **本模块独有**：``_migrate_core_memory_layout``（旧版 ``memory/`` 合并进
  ``memories/core_memory/``，data_paths 侧没有对应副本）；
- ``run_all_migrations``：公开的「全量迁移」聚合入口，供诊断脚本与测试调用。

⚠️ 线上启动路径是 ``data_paths._ensure_initialized``，它只调用 4 个迁移
（legacy 布局 / 角色布局 / 自主进食 / persona export），**不调用**
``_migrate_core_memory_layout``。是否把它并进启动路径是独立决策，不要在重构里顺手改。
"""
from pathlib import Path

import structlog

# ── 迁移实现（唯一副本在 data_paths）──────────────────────────────────────
from .data_paths import (
    _is_ling_persona_name as _is_ling_persona_name,
    _iter_existing_chat_history_roots as iter_existing_chat_history_roots,
    _migrate_active_care_layout as _migrate_active_care_layout,
    _migrate_daily_diary_layout as _migrate_daily_diary_layout,
    _migrate_daily_event_layout as _migrate_daily_event_layout,
    _migrate_legacy_layout as _migrate_legacy_layout,
    _migrate_misplaced_memory_files as _migrate_misplaced_memory_files,
    _migrate_persona_export_layout as _migrate_persona_export_layout,
    _migrate_role_layout as _migrate_role_layout,
    _migrate_self_meals_from_user_records as _migrate_self_meals_from_user_records,
    _migrate_user_chat_history_layout as _migrate_user_chat_history_layout,
    _move_path_merge as _move_path_merge,
    _resolve_scope_from_chat_history_path as _resolve_scope_from_chat_history_path,
    _scope_to_chat_history_root as _scope_to_chat_history_root,
    _split_daily_event_scope as _split_daily_event_scope,
    _target_chat_history_parts as _target_chat_history_parts,
)

# ── 兼容旧诊断脚本引用的路径常量与 scope 集合（真源仍在 data_paths / scope_registry）──
from .data_paths import (
    _AVELINE_DIR as _AVELINE_DIR,
    _BASE_NAME as _BASE_NAME,
    _LEGACY_BASE_NAME as _LEGACY_BASE_NAME,
    _LING_DIR as _LING_DIR,
    _LING_SELF_MEAL_PREFIXES as _LING_SELF_MEAL_PREFIXES,
    _USER_DIR as _USER_DIR,
    _XIAOLU_DIR as _XIAOLU_DIR,
    _YEYE_DIR as _YEYE_DIR,
)
from .scope_registry import (
    _DYNAMIC_SCOPES as _DYNAMIC_SCOPES,
    _VALID_SCOPES as _VALID_SCOPES,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "iter_existing_chat_history_roots",
    "run_all_migrations",
]


def _migrate_core_memory_layout(base: Path) -> None:
    """将各角色目录下旧版 memory/（核心记忆归档与每日日志）合并进 memories/core_memory/。

    旧布局：{role}_data/memory/{archive/, YYYY-MM-DD.md}
    新布局：{role}_data/memories/core_memory/{archive/, YYYY-MM-DD.md}
    避免与对话记忆系统的 memories/ 目录名称混淆。
    """
    if not base.exists():
        return
    for role_dir in list(base.iterdir()):
        if not role_dir.is_dir():
            continue
        legacy_memory = (role_dir / "memory").resolve()
        if not legacy_memory.is_dir():
            continue
        target = (role_dir / "memories" / "core_memory").resolve()
        try:
            _move_path_merge(legacy_memory, target)
        except Exception:
            logger.warning(
                "迁移核心记忆目录失败", src=str(legacy_memory), dst=str(target), exc_info=True
            )


def run_all_migrations(base: Path, project_root: Path) -> None:
    """执行全部数据布局迁移（聚合入口，非启动路径）。

    Args:
        base: companion_data 根目录
        project_root: 项目根目录
    """
    _migrate_legacy_layout(project_root)
    _migrate_role_layout(base)
    _migrate_self_meals_from_user_records(base)
    _migrate_persona_export_layout(base)
    _migrate_core_memory_layout(base)
