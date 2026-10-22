// 新增能力的 API 封装。
//
// 为什么单独一个文件：apiService.ts 已经有 1100+ 行（历史存量），继续往里塞
// 会让它更难维护；这里只做「端点 -> 类型化函数」的薄封装，复用同一个请求层，
// 保证鉴权头、超时与错误处理口径一致。
import apiClient from './apiService';
import type {
  ConversationSummary,
  DiaryEntry,
  LifeStatusPayload,
  NotificationItem,
  RoleProfile,
  StudyNoteItem,
  VocabSessionStats,
  WeightedMemoryItem,
} from '../types/features';

const get = apiClient.get;
const post = apiClient.post;
const put = apiClient.put;
const del = apiClient.delete;

/** 后端响应有两种口径：裸对象与 `{status,data}`，统一取 data。 */
export const unwrap = <T,>(response: any, fallback: T): T => {
  if (response && typeof response === 'object' && 'data' in response && response.data != null) {
    return response.data as T;
  }
  return (response ?? fallback) as T;
};

export const featureApi = {
  // ===== 会话 =====
  listConversations: async (includeExternal = true): Promise<ConversationSummary[]> => {
    const res = await get('/api/v1/sessions', { include_external: includeExternal }, { retries: 0 });
    const list = Array.isArray(res?.data) ? res.data : [];
    return list.filter((item: any) => item && item.id && item.id !== 'null');
  },
  createConversation: async (title?: string) => {
    const res = await post('/api/v1/sessions', { title });
    return res?.data || res;
  },
  renameConversation: async (id: string, title: string) => {
    return put(`/api/v1/sessions/${encodeURIComponent(id)}`, { title });
  },
  deleteConversation: async (id: string) => {
    return del(`/api/v1/sessions/${encodeURIComponent(id)}`);
  },

  // ===== 角色资料 =====
  listRoles: async (): Promise<RoleProfile[]> => {
    const res = await get('/api/v1/roles', undefined, { retries: 0 });
    return unwrap<{ roles?: RoleProfile[] }>(res, {}).roles || [];
  },
  updateRole: async (
    scope: string,
    patch: { display_name?: string; avatar?: string; voice_id?: string },
  ): Promise<RoleProfile | null> => {
    const res = await put(`/api/v1/roles/${encodeURIComponent(scope)}`, patch);
    return unwrap<{ role?: RoleProfile }>(res, {}).role || null;
  },

  // ===== 通知中心 =====
  listNotifications: async (userId = 'default_user') => {
    const res = await get('/api/v1/notifications', { user_id: userId }, { retries: 0 });
    const data = unwrap<{ items?: NotificationItem[]; unread?: number }>(res, {});
    return { items: data.items || [], unread: Number(data.unread || 0) };
  },
  markNotificationsRead: async (ids?: string[], userId = 'default_user') => {
    const res = await post('/api/v1/notifications/read', { user_id: userId, ids });
    return unwrap<{ marked?: number; unread?: number }>(res, {});
  },
  pushNotification: async (payload: {
    title: string;
    content: string;
    type?: string;
    user_id?: string;
  }) => {
    return post('/api/v1/notifications', payload);
  },

  // ===== 伴侣详情 / 生命状态 =====
  getLifeStatus: async (scope: string, persona?: string): Promise<LifeStatusPayload> => {
    const res = await get('/api/v1/life/status', { scope, persona }, { retries: 0 });
    return (res || {}) as LifeStatusPayload;
  },
  wakeRole: async (payload: { role_id?: string; conversation_id?: string; message?: string }) => {
    return post('/api/v1/life/sleep/wake', payload);
  },
  interruptActivity: async (payload: { role_id?: string; conversation_id?: string; message?: string }) => {
    return post('/api/v1/life/activity/interrupt', payload);
  },
  skipActivity: async (payload: { role_id?: string; conversation_id?: string; message?: string }) => {
    return post('/api/v1/life/activity/skip', payload);
  },
  extendActivity: async (payload: {
    role_id?: string;
    conversation_id?: string;
    extend_seconds?: number;
    message?: string;
  }) => {
    return post('/api/v1/life/activity/extend', payload);
  },

  // ===== 人设 / 音色 / 模型 =====
  listPersonas: async () => {
    const res = await get('/api/v1/personas');
    return Array.isArray(res) ? res : res?.data || [];
  },
  switchPersona: async (filename: string) => post('/api/v1/personas/switch', { filename }),
  getCurrentPersona: async () => {
    const res = await get('/api/v1/personas/current', undefined, { retries: 0 });
    return res || {};
  },
  listVoices: async (): Promise<Array<{ id: string; name: string }>> => {
    const res = await get('/api/v1/media/voices', undefined, { retries: 0 });
    return unwrap<{ voices?: Array<{ id: string; name: string }> }>(res, {}).voices || [];
  },

  // ===== 记忆世界线 =====
  listMemories: async (params: { limit?: number; minWeight?: number; persona?: string }) => {
    const res = await get('/api/v1/memories', {
      limit: params.limit ?? 120,
      min_weight: params.minWeight ?? 0.1,
      persona: params.persona,
    });
    const data = unwrap<{ memories?: WeightedMemoryItem[] } | WeightedMemoryItem[]>(res, []);
    if (Array.isArray(data)) return data;
    return data.memories || [];
  },
  deleteMemory: async (id: string) => del(`/api/v1/memories/${encodeURIComponent(id)}`),
  clearMemories: async (mode: 'all' | 'short' = 'short', userId?: string) =>
    post('/api/v1/memories/clear', { mode, user_id: userId }),

  // ===== 隐私与偏好 =====
  getPreferences: async () => {
    const res = await get('/api/v1/system/preferences', undefined, { retries: 0 });
    return unwrap<Record<string, unknown>>(res, {});
  },
  updatePreferences: async (prefs: Record<string, unknown>) =>
    post('/api/v1/system/preferences', prefs),
  getSensitiveStatus: async () => {
    const res = await get('/api/v1/plugins/variants/status', undefined, { retries: 0 });
    return unwrap<Record<string, unknown>>(res, {});
  },
  toggleSensitive: async (enabled: boolean) =>
    post('/api/v1/plugins/variants/toggle', { enabled }),

  // ===== 学习：笔记 / 日记 / 词汇会话 =====
  listStudyNotes: async (): Promise<StudyNoteItem[]> => {
    const res = await get('/api/v1/study-daily/notes', undefined, { retries: 0 });
    const data = unwrap<{ notes?: StudyNoteItem[] }>(res, {});
    return (data.notes || []).map((note: any) => ({
      filename: String(note.filename || note.name || ''),
      path: note.path,
      title: note.title || note.filename || note.name,
      updated_at: note.updated_at || note.mtime,
      size: note.size,
    })).filter((note) => note.filename);
  },
  readStudyNote: async (filename: string) => {
    const res = await get(
      `/api/v1/study-daily/notes/${encodeURIComponent(filename)}`,
      undefined,
      { retries: 0 },
    );
    return unwrap<{ content?: string; filename?: string; title?: string }>(res, {});
  },
  listDiary: async (date?: string): Promise<DiaryEntry[]> => {
    const res = await get('/api/v1/diary', date ? { date } : undefined, { retries: 0 });
    if (Array.isArray(res)) return res;
    const data = unwrap<DiaryEntry[] | { entries?: DiaryEntry[] }>(res, []);
    return Array.isArray(data) ? data : data.entries || [];
  },
  getVocabSessionStats: async (): Promise<VocabSessionStats> => {
    const res = await get('/api/v1/vocab/sessions/stats', undefined, { retries: 0 });
    return unwrap<VocabSessionStats>(res, {});
  },
  getVocabSummary: async () => {
    const res = await get('/api/v1/vocab/summary', undefined, { retries: 0 });
    return unwrap<Record<string, unknown>>(res, {});
  },
  startVocabSession: async () => post('/api/v1/vocab/sessions', {}),
  endVocabSession: async () => del('/api/v1/vocab/sessions/current'),
};

export type FeatureApi = typeof featureApi;
