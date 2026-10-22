import React, { useMemo, useState } from 'react';
import {
  Check,
  MessagesSquare,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Users,
  X,
} from 'lucide-react';
import { useFeatureStore } from '../../store/useFeatureStore';
import { conversationDisplayTitle, relativeTime } from '../../utils/conversation';
import RoleProfileEditor from './RoleProfileEditor';

interface ConversationsPanelProps {
  currentSessionId: string | null;
  onSelectConversation: (conversationId: string) => void;
  onRequestConfirm?: (options: {
    title: string;
    message: string;
    onConfirm: () => void;
    onCancel?: () => void;
    type?: 'danger' | 'info' | 'warning';
    showCancel?: boolean;
    confirmText?: string;
    cancelText?: string;
  }) => void;
}

const ROLE_LABELS: Record<string, string> = {
  user: '我的工作区',
  unknown: '其他会话',
};

/** 多角色会话管理：分组列表 + 重命名/删除 + 角色资料编辑。 */
const ConversationsPanel: React.FC<ConversationsPanelProps> = ({
  currentSessionId,
  onSelectConversation,
  onRequestConfirm,
}) => {
  const conversations = useFeatureStore((s) => s.conversations);
  const roles = useFeatureStore((s) => s.roles);
  const loading = useFeatureStore((s) => s.conversationsLoading);
  const includeExternal = useFeatureStore((s) => s.includeExternal);
  const setIncludeExternal = useFeatureStore((s) => s.setIncludeExternal);
  const loadConversations = useFeatureStore((s) => s.loadConversations);
  const loadRoles = useFeatureStore((s) => s.loadRoles);
  const groupConversationsByRole = useFeatureStore((s) => s.groupConversationsByRole);
  const createConversation = useFeatureStore((s) => s.createConversation);
  const renameConversation = useFeatureStore((s) => s.renameConversation);
  const deleteConversation = useFeatureStore((s) => s.deleteConversation);
  const markConversationRead = useFeatureStore((s) => s.markConversationRead);

  const [query, setQuery] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  const [selectedScope, setSelectedScope] = useState<string>('user');

  const groups = useMemo(() => {
    const all = groupConversationsByRole();
    const keyword = query.trim().toLowerCase();
    if (!keyword) return all;
    return all
      .map((group) => ({
        ...group,
        conversations: group.conversations.filter((conversation) =>
          conversationDisplayTitle(conversation.title, conversation.id)
            .toLowerCase()
            .includes(keyword),
        ),
      }))
      .filter((group) => group.conversations.length > 0);
  }, [groupConversationsByRole, query, conversations, roles]);

  const roleName = (scope: string) => {
    const profile = roles.find((role) => role.scope === scope);
    return profile?.display_name || profile?.name || ROLE_LABELS[scope] || scope;
  };
  const roleAvatar = (scope: string) => {
    const profile = roles.find((role) => role.scope === scope);
    return profile?.avatar || (scope === 'user' ? '🏠' : '🪐');
  };

  const handleCreate = async () => {
    const id = await createConversation();
    if (id) {
      markConversationRead(id);
      onSelectConversation(id);
    }
  };

  const submitRename = async (conversationId: string) => {
    const title = editingTitle.trim();
    if (title) await renameConversation(conversationId, title);
    setEditingId(null);
    setEditingTitle('');
  };

  const requestDelete = (conversationId: string, title: string) => {
    const run = async () => {
      await deleteConversation(conversationId);
    };
    if (onRequestConfirm) {
      onRequestConfirm({
        title: '删除会话',
        message: `确定删除「${title}」？该会话的历史消息会一并从列表移除。`,
        type: 'danger',
        confirmText: '删除',
        cancelText: '取消',
        onConfirm: () => void run(),
      });
      return;
    }
    void run();
  };

  return (
    <div className="flex h-full min-h-0">
      {/* 会话列表 */}
      <div className="w-[58%] min-w-[320px] border-r border-white/5 flex flex-col min-h-0">
        <div className="p-4 space-y-3 border-b border-white/5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-white/80">
              <MessagesSquare size={16} className="text-emerald-400" />
              <span className="text-sm tracking-wide">会话</span>
              <span className="text-[11px] text-white/30 font-mono">
                {conversations.length}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  void loadConversations();
                  void loadRoles();
                }}
                className="p-1.5 rounded-lg text-white/40 hover:text-white hover:bg-white/10 transition-colors"
                title="刷新"
              >
                <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
              </button>
              <button
                onClick={() => void handleCreate()}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-emerald-500/15 text-emerald-200 border border-emerald-500/25 hover:bg-emerald-500/25 text-xs transition-colors"
              >
                <Plus size={13} /> 新建
              </button>
            </div>
          </div>

          <div className="flex items-center gap-2 bg-black/30 border border-white/10 rounded-lg px-2.5 py-1.5">
            <Search size={13} className="text-white/30" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索会话标题"
              className="flex-1 bg-transparent outline-none text-xs text-white placeholder:text-white/25"
            />
            {query && (
              <button onClick={() => setQuery('')} className="text-white/30 hover:text-white">
                <X size={12} />
              </button>
            )}
          </div>

          <label className="flex items-center gap-2 text-[11px] text-white/40 select-none">
            <input
              type="checkbox"
              checked={includeExternal}
              onChange={(event) => setIncludeExternal(event.target.checked)}
              className="accent-emerald-500"
            />
            显示全部来源会话（含 QQ / 群聊等外部会话）
          </label>
        </div>

        <div className="flex-1 overflow-y-auto custom-scrollbar p-3 space-y-4">
          {groups.length === 0 && (
            <div className="text-xs text-white/30 text-center py-10">
              {loading ? '加载中…' : '没有匹配的会话'}
            </div>
          )}

          {groups.map((group) => (
            <div key={group.scope} className="space-y-1">
              <div className="flex items-center gap-2 px-2 py-1">
                <span className="text-sm">{roleAvatar(group.scope)}</span>
                <span className="text-[11px] uppercase tracking-wider text-white/40">
                  {roleName(group.scope)}
                </span>
                <span className="text-[10px] text-white/25 font-mono">
                  {group.conversations.length}
                </span>
                <button
                  onClick={() => setSelectedScope(group.scope)}
                  className={`ml-auto text-[10px] px-2 py-0.5 rounded-md border transition-colors ${
                    selectedScope === group.scope
                      ? 'text-emerald-200 border-emerald-500/30 bg-emerald-500/10'
                      : 'text-white/35 border-white/10 hover:text-white/70'
                  }`}
                >
                  资料
                </button>
              </div>

              {group.conversations.map((conversation) => {
                const active = conversation.id === currentSessionId;
                const title = conversationDisplayTitle(conversation.title, conversation.id);
                return (
                  <div
                    key={conversation.id}
                    className={`group flex items-center gap-2 px-2.5 py-2 rounded-lg border transition-all ${
                      active
                        ? 'bg-white/10 border-white/15 text-white'
                        : 'border-transparent text-white/60 hover:bg-white/5 hover:text-white/90'
                    }`}
                  >
                    {editingId === conversation.id ? (
                      <input
                        autoFocus
                        value={editingTitle}
                        onChange={(event) => setEditingTitle(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') void submitRename(conversation.id);
                          if (event.key === 'Escape') setEditingId(null);
                        }}
                        className="flex-1 bg-black/40 border border-white/15 rounded-md px-2 py-1 text-xs text-white outline-none"
                      />
                    ) : (
                      <button
                        onClick={() => {
                          markConversationRead(conversation.id);
                          onSelectConversation(conversation.id);
                        }}
                        className="flex-1 min-w-0 text-left"
                      >
                        <span className="flex items-center gap-1.5">
                          <span className="text-xs truncate">{title}</span>
                          {conversation.unread ? (
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
                          ) : null}
                        </span>
                        <span className="block text-[10px] text-white/25 mt-0.5 font-mono truncate">
                          {relativeTime(conversation.updated_at)} · {conversation.id.slice(0, 12)}
                        </span>
                      </button>
                    )}

                    {editingId === conversation.id ? (
                      <button
                        onClick={() => void submitRename(conversation.id)}
                        className="p-1 rounded text-emerald-300 hover:bg-emerald-500/15"
                        title="保存标题"
                      >
                        <Check size={12} />
                      </button>
                    ) : (
                      <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={() => {
                            setEditingId(conversation.id);
                            setEditingTitle(title);
                          }}
                          className="p-1 rounded text-white/40 hover:text-white hover:bg-white/10"
                          title="重命名"
                        >
                          <Pencil size={11} />
                        </button>
                        <button
                          onClick={() => requestDelete(conversation.id, title)}
                          className="p-1 rounded text-white/40 hover:text-red-300 hover:bg-red-500/15"
                          title="删除"
                        >
                          <Trash2 size={11} />
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* 角色资料 */}
      <div className="flex-1 min-w-0 overflow-y-auto custom-scrollbar p-5">
        <div className="flex items-center gap-2 mb-4">
          <Users size={16} className="text-emerald-400" />
          <span className="text-sm text-white/85">角色资料</span>
        </div>

        <div className="flex flex-wrap gap-1.5 mb-5">
          {roles.map((role) => (
            <button
              key={role.scope}
              onClick={() => setSelectedScope(role.scope)}
              className={`px-2.5 py-1 rounded-lg text-[11px] border transition-colors ${
                selectedScope === role.scope
                  ? 'bg-emerald-500/15 text-emerald-200 border-emerald-500/30'
                  : 'text-white/45 border-white/10 hover:text-white/80 hover:bg-white/5'
              }`}
            >
              {role.avatar || '🪐'} {role.display_name || role.name}
            </button>
          ))}
          {roles.length === 0 && (
            <span className="text-[11px] text-white/30">未读取到后端角色清单</span>
          )}
        </div>

        <div className="rounded-2xl border border-white/10 bg-black/25 p-5">
          <RoleProfileEditor scope={selectedScope} fallbackName={roleName(selectedScope)} />
        </div>

        <div className="mt-5 rounded-2xl border border-white/5 bg-black/20 p-4 text-[11px] leading-relaxed text-white/40">
          昵称、头像与音色保存在后端 <code className="text-white/60">companion_data/role_profiles.json</code>，
          所有客户端共用一份；会话列表按会话 ID 反解角色归属，无法反解的会话归入「其他会话」。
        </div>
      </div>
    </div>
  );
};

export default ConversationsPanel;
