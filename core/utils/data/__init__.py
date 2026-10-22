"""
Data / 数据路径与范围注册 子包。

原 core.utils.data_paths / data_paths_migrations / scope_registry /
conversation_labels 已分组到此子包。本文件 re-export 全部公开符号。
"""

from core.utils.data.conversation_labels import *
from core.utils.data.data_paths import *
from core.utils.data.data_paths_migrations import *
from core.utils.data.scope_registry import *

__all__ = [
    "is_external_or_internal_conversation_id",
    "is_primary_user_conversation_id",
    "get_conversation_label_info",
    "get_project_root",
    "get_companion_data_dir",
    "get_user_data_dir",
    "get_aveline_data_dir",
    "get_ling_data_dir",
    "get_role_data_dir",
    "get_xiaolu_data_dir",
    "get_yeye_data_dir",
    "get_dual_role_data_dir",
    "get_dual_role_reminder_assignment_path",
    "get_proactive_assignment_path",
    "get_user_daily_dir",
    "get_user_daily_records_dir",
    "get_user_chat_history_dir",
    "get_user_weighted_history_dir",
    "get_role_chat_history_dir",
    "get_chat_history_dir_for_conversation",
    "get_all_chat_history_dirs",
    "get_user_schedule_dir",
    "get_user_status_dir",
    "get_user_reminders_file",
    "get_user_latest_device_context_file",
    "get_aveline_life_dir",
    "get_aveline_life_records_dir",
    "get_ling_life_dir",
    "get_ling_life_records_dir",
    "get_aveline_persona_data_dir",
    "get_ling_persona_data_dir",
    "get_role_profiles_dir",
    "get_role_profile_path",
    "get_user_person_profile_path",
    "get_user_people_profiles_dir",
    "get_user_people_profile_path",
    "get_role_daily_dir",
    "get_active_care_dir",
    "get_background_circle_dir",
    "get_study_root_dir",
    "get_study_daily_dir",
    "get_study_daily_date_dir",
    "run_all_migrations",
    "normalize_data_scope",
    "init_scope_registry",
    "refresh_scope_registry",
    "get_registered_role_scopes",
    "resolve_active_persona_scope",
    "resolve_persona_slug_scope",
    "resolve_data_scope_from_conversation_id",
    "resolve_data_scope_from_source",
    "resolve_memory_user_id",
    "get_dynamic_scope_dir_name",
    "list_dynamic_scopes",
]
