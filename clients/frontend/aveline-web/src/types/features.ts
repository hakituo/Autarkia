// 多角色会话 / 通知中心 / 伴侣详情等新增能力的共享类型定义。
// 后端字段一律保持 snake_case，避免中间层再做一次映射。

export interface ConversationSummary {
  id: string;
  title: string;
  created_at?: number;
  updated_at: number;
  /** 归属角色 scope（前端按会话 ID 反解，未知时为 "unknown"） */
  roleScope?: string;
  /** 本地未读数（当前实现为「有更新且未打开」，最多显示 1 条徽章语义） */
  unread?: number;
  lastReadAt?: number;
}

export interface RoleProfile {
  scope: string;
  name: string;
  display_name: string;
  avatar: string;
  voice_id: string;
  persona_file: string;
  voice_file?: string;
  aliases: string[];
  overridden?: boolean;
}

export interface NotificationItem {
  id: string;
  type: string;
  title: string;
  content: string;
  payload?: Record<string, unknown>;
  timestamp: number;
  read: boolean;
}

export interface DailyPlanActivity {
  activity?: string;
  label?: string;
  start?: string;
  end?: string;
  description?: string;
  [key: string]: unknown;
}

export interface DailyPlan {
  date?: string;
  activities?: DailyPlanActivity[];
  current_activity?: string;
  [key: string]: unknown;
}

export interface LifeStatusPayload {
  status?: string;
  life_status?: Record<string, number>;
  emotion?: string;
  activity?: string;
  activity_chat_eligible?: boolean;
  reply_policy?: Record<string, unknown>;
  sleep_summary?: Record<string, unknown>;
  daily_plan?: DailyPlan | null;
  scope?: string;
}

export interface WeightedMemoryItem {
  id: string;
  content: string;
  timestamp: number;
  weight: number;
  topics?: string[];
  emotions?: string[];
  is_important?: boolean;
  source?: string;
}

export interface DiaryEntry {
  id: string;
  timestamp: number;
  time_str?: string;
  type?: string;
  content: string;
  thought?: string;
  mood?: string;
  tags?: string[];
  source?: string;
  source_label?: string;
}

export interface StudyNoteItem {
  filename: string;
  path?: string;
  title?: string;
  updated_at?: number;
  size?: number;
}

export interface VocabSessionStats {
  total?: number;
  reviewed?: number;
  correct?: number;
  accuracy?: number;
  started_at?: number;
  duration_seconds?: number;
  [key: string]: unknown;
}

export interface AttachmentDraft {
  id: string;
  file: File;
  preview?: string;
  kind: 'image' | 'file';
}

export interface MessageVersionEntry {
  versions: string[];
  index: number;
}

export interface DraftMap {
  [conversationId: string]: string;
}

export interface RoleScopeGroup {
  scope: string;
  profile: RoleProfile | null;
  conversations: ConversationSummary[];
}
