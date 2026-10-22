// 多角色会话 / 角色资料 / 通知中心 / 草稿 / 消息版本 的共享状态。
//
// 与 useStore.ts（聊天消息本体）分开：这里是「会话层」数据，切换会话时不需要
// 重建消息 store，避免把聊天主路径的状态搅在一起。
import { create } from 'zustand';
import { featureApi } from '../api/featureApi';
import type {
  ConversationSummary,
  DraftMap,
  MessageVersionEntry,
  NotificationItem,
  RoleProfile,
  RoleScopeGroup,
} from '../types/features';
import {
  isConversationUnread,
  loadReadMarkers,
  resolveRoleScopeFromConversationId,
  saveReadMarker,
} from '../utils/conversation';

const DRAFTS_KEY = 'aveline_drafts_v1';

const loadDrafts = (): DraftMap => {
  try {
    const raw = localStorage.getItem(DRAFTS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
};

const persistDrafts = (drafts: DraftMap) => {
  try {
    localStorage.setItem(DRAFTS_KEY, JSON.stringify(drafts));
  } catch {
    // 忽略配额/隐私模式下的写入失败
  }
};

interface FeatureState {
  // 会话
  conversations: ConversationSummary[];
  conversationsLoading: boolean;
  conversationsError: string | null;
  readMarkers: Record<string, number>;
  includeExternal: boolean;
  loadConversations: (options?: { includeExternal?: boolean; silent?: boolean }) => Promise<void>;
  markConversationRead: (conversationId: string) => void;
  createConversation: (title?: string) => Promise<string | null>;
  renameConversation: (conversationId: string, title: string) => Promise<boolean>;
  deleteConversation: (conversationId: string) => Promise<boolean>;
  setIncludeExternal: (value: boolean) => void;
  groupConversationsByRole: () => RoleScopeGroup[];

  // 角色资料
  roles: RoleProfile[];
  rolesLoading: boolean;
  loadRoles: () => Promise<void>;
  saveRole: (
    scope: string,
    patch: { display_name?: string; avatar?: string; voice_id?: string },
  ) => Promise<boolean>;
  roleForScope: (scope: string) => RoleProfile | null;

  // 通知
  notifications: NotificationItem[];
  notificationsLoading: boolean;
  unreadNotifications: number;
  loadNotifications: () => Promise<void>;
  markNotificationsRead: (ids?: string[]) => Promise<void>;

  // 草稿
  drafts: DraftMap;
  setDraft: (conversationId: string, text: string) => void;
  clearDraft: (conversationId: string) => void;

  // 消息多版本
  versions: Record<string, MessageVersionEntry>;
  pushVersion: (messageId: string, text: string) => void;
  switchVersion: (messageId: string, delta: number) => string | null;
  getVersionState: (messageId: string) => MessageVersionEntry | null;
}

export const useFeatureStore = create<FeatureState>((set, get) => ({
  conversations: [],
  conversationsLoading: false,
  conversationsError: null,
  readMarkers: loadReadMarkers(),
  includeExternal: false,

  loadConversations: async (options) => {
    const includeExternal = options?.includeExternal ?? get().includeExternal;
    if (!options?.silent) set({ conversationsLoading: true, conversationsError: null });
    try {
      const list = await featureApi.listConversations(includeExternal);
      const markers = get().readMarkers;
      const mapped: ConversationSummary[] = list
        .map((item) => {
          const roleScope = resolveRoleScopeFromConversationId(item.id);
          const updatedAt = Number(item.updated_at || item.created_at || 0);
          return {
            ...item,
            updated_at: updatedAt,
            roleScope,
            lastReadAt: markers[item.id] || 0,
            unread: isConversationUnread(updatedAt, item.id, markers) ? 1 : 0,
          };
        })
        .sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
      set({ conversations: mapped, conversationsLoading: false });
    } catch (error: any) {
      set({
        conversationsLoading: false,
        conversationsError: error?.message || '会话列表加载失败',
      });
    }
  },

  markConversationRead: (conversationId) => {
    if (!conversationId) return;
    const now = Math.floor(Date.now() / 1000);
    saveReadMarker(conversationId, now);
    const markers = loadReadMarkers();
    set((state) => ({
      readMarkers: markers,
      conversations: state.conversations.map((item) =>
        item.id === conversationId ? { ...item, unread: 0, lastReadAt: now } : item,
      ),
    }));
  },

  createConversation: async (title) => {
    try {
      const created = await featureApi.createConversation(title);
      const id = String(created?.id || '');
      await get().loadConversations({ silent: true });
      if (id) get().markConversationRead(id);
      return id || null;
    } catch {
      return null;
    }
  },

  renameConversation: async (conversationId, title) => {
    const next = String(title || '').trim();
    if (!conversationId || !next) return false;
    try {
      await featureApi.renameConversation(conversationId, next);
      set((state) => ({
        conversations: state.conversations.map((item) =>
          item.id === conversationId ? { ...item, title: next } : item,
        ),
      }));
      return true;
    } catch {
      return false;
    }
  },

  deleteConversation: async (conversationId) => {
    if (!conversationId) return false;
    try {
      await featureApi.deleteConversation(conversationId);
      set((state) => ({
        conversations: state.conversations.filter((item) => item.id !== conversationId),
      }));
      return true;
    } catch {
      return false;
    }
  },

  setIncludeExternal: (value) => {
    set({ includeExternal: value });
    void get().loadConversations({ includeExternal: value });
  },

  groupConversationsByRole: () => {
    const { conversations, roles } = get();
    const groups = new Map<string, RoleScopeGroup>();
    const roleByScope = new Map(roles.map((role) => [role.scope, role]));

    conversations.forEach((conversation) => {
      const scope = conversation.roleScope || 'unknown';
      if (!groups.has(scope)) {
        groups.set(scope, {
          scope,
          profile: roleByScope.get(scope) || null,
          conversations: [],
        });
      }
      groups.get(scope)!.conversations.push(conversation);
    });

    return Array.from(groups.values()).sort((a, b) => {
      const aTime = a.conversations[0]?.updated_at || 0;
      const bTime = b.conversations[0]?.updated_at || 0;
      return bTime - aTime;
    });
  },

  roles: [],
  rolesLoading: false,

  loadRoles: async () => {
    set({ rolesLoading: true });
    try {
      const roles = await featureApi.listRoles();
      set({ roles, rolesLoading: false });
    } catch {
      set({ rolesLoading: false });
    }
  },

  saveRole: async (scope, patch) => {
    try {
      const updated = await featureApi.updateRole(scope, patch);
      if (updated) {
        set((state) => ({
          roles: state.roles.some((role) => role.scope === updated.scope)
            ? state.roles.map((role) => (role.scope === updated.scope ? updated : role))
            : [...state.roles, updated],
        }));
      }
      return true;
    } catch {
      return false;
    }
  },

  roleForScope: (scope) => get().roles.find((role) => role.scope === scope) || null,

  notifications: [],
  notificationsLoading: false,
  unreadNotifications: 0,

  loadNotifications: async () => {
    set({ notificationsLoading: true });
    try {
      const { items, unread } = await featureApi.listNotifications();
      set({ notifications: items, unreadNotifications: unread, notificationsLoading: false });
    } catch {
      set({ notificationsLoading: false });
    }
  },

  markNotificationsRead: async (ids) => {
    try {
      const result = await featureApi.markNotificationsRead(ids);
      set((state) => ({
        notifications: state.notifications.map((item) =>
          !ids || ids.includes(item.id) ? { ...item, read: true } : item,
        ),
        unreadNotifications: Number(result.unread ?? 0),
      }));
    } catch {
      // 离线时保留本地未读状态，下次轮询再同步
    }
  },

  drafts: loadDrafts(),

  setDraft: (conversationId, text) => {
    const key = conversationId || 'default_user';
    const next = { ...get().drafts, [key]: text };
    persistDrafts(next);
    set({ drafts: next });
  },

  clearDraft: (conversationId) => {
    const key = conversationId || 'default_user';
    const next = { ...get().drafts };
    delete next[key];
    persistDrafts(next);
    set({ drafts: next });
  },

  versions: {},

  pushVersion: (messageId, text) => {
    const key = String(messageId);
    set((state) => {
      const existing = state.versions[key];
      const versions = existing ? [...existing.versions, text] : [text];
      return {
        versions: {
          ...state.versions,
          [key]: { versions, index: versions.length - 1 },
        },
      };
    });
  },

  switchVersion: (messageId, delta) => {
    const key = String(messageId);
    const entry = get().versions[key];
    if (!entry || entry.versions.length < 2) return null;
    const nextIndex = Math.min(
      entry.versions.length - 1,
      Math.max(0, entry.index + delta),
    );
    set((state) => ({
      versions: { ...state.versions, [key]: { ...entry, index: nextIndex } },
    }));
    return entry.versions[nextIndex];
  },

  getVersionState: (messageId) => get().versions[String(messageId)] || null,
}));

export default useFeatureStore;
