import React, { useEffect, useMemo } from 'react';
import { MessageSquarePlus, Plus, Settings2, Sparkles } from 'lucide-react';
import { useFeatureStore } from '../../store/useFeatureStore';
import { conversationDisplayTitle, relativeTime } from '../../utils/conversation';

interface ConversationSidebarProps {
  currentSessionId: string | null;
  onSelectConversation: (conversationId: string) => void;
  onCreateConversation: () => Promise<void> | void;
  isExpanded: boolean;
  onOpenManager?: () => void;
}

const ROLE_LABELS: Record<string, string> = {
  user: '我的工作区',
  unknown: '其他会话',
};

/** 侧边栏里的多角色会话列表：按角色分组 + 未读徽章 + 新建话题。 */
export const ConversationSidebar: React.FC<ConversationSidebarProps> = ({
  currentSessionId,
  onSelectConversation,
  onCreateConversation,
  isExpanded,
  onOpenManager,
}) => {
  const conversations = useFeatureStore((s) => s.conversations);
  const roles = useFeatureStore((s) => s.roles);
  const loading = useFeatureStore((s) => s.conversationsLoading);
  const loadConversations = useFeatureStore((s) => s.loadConversations);
  const loadRoles = useFeatureStore((s) => s.loadRoles);
  const groupConversationsByRole = useFeatureStore((s) => s.groupConversationsByRole);
  const markConversationRead = useFeatureStore((s) => s.markConversationRead);

  useEffect(() => {
    void loadRoles();
    void loadConversations();
    const timer = window.setInterval(() => {
      void loadConversations({ silent: true });
    }, 20000);
    return () => window.clearInterval(timer);
  }, [loadConversations, loadRoles]);

  const groups = useMemo(() => groupConversationsByRole(), [
    conversations,
    roles,
    groupConversationsByRole,
  ]);

  const roleName = (scope: string) => {
    const profile = roles.find((role) => role.scope === scope);
    return profile?.display_name || profile?.name || ROLE_LABELS[scope] || scope;
  };
  const roleAvatar = (scope: string) => {
    const profile = roles.find((role) => role.scope === scope);
    return profile?.avatar || (scope === 'user' ? '🏠' : '🪐');
  };

  const handleSelect = (conversationId: string) => {
    markConversationRead(conversationId);
    onSelectConversation(conversationId);
  };

  if (!isExpanded) {
    return (
      <div className="mt-2 space-y-1">
        {groups.slice(0, 5).map((group) => {
          const unread = group.conversations.some((item) => item.unread);
          return (
            <button
              key={group.scope}
              onClick={() => {
                const target = group.conversations[0];
                if (target) handleSelect(target.id);
              }}
              title={`${roleName(group.scope)}（${group.conversations.length} 个会话）`}
              className="w-full h-9 flex items-center justify-center rounded-lg hover:bg-white/5 relative text-base"
            >
              <span>{roleAvatar(group.scope)}</span>
              {unread && (
                <span className="absolute top-1.5 right-2 w-1.5 h-1.5 rounded-full bg-emerald-400" />
              )}
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div className="mt-3 flex flex-col min-h-0 flex-1">
      <div className="flex items-center justify-between px-2 mb-2">
        <span className="text-[10px] uppercase tracking-[0.18em] text-white/30">会话</span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => void onCreateConversation()}
            className="p-1 rounded-md text-white/40 hover:text-white hover:bg-white/10 transition-colors"
            title="新建话题"
          >
            <Plus size={13} />
          </button>
          {onOpenManager && (
            <button
              onClick={onOpenManager}
              className="p-1 rounded-md text-white/40 hover:text-white hover:bg-white/10 transition-colors"
              title="会话与角色管理"
            >
              <Settings2 size={13} />
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar space-y-3 pr-1">
        {loading && conversations.length === 0 && (
          <div className="text-[11px] text-white/30 px-2 py-3">加载会话…</div>
        )}
        {!loading && conversations.length === 0 && (
          <div className="text-[11px] text-white/25 px-2 py-3 flex items-center gap-1.5">
            <Sparkles size={12} /> 还没有会话，点 + 开一个
          </div>
        )}

        {groups.map((group) => (
          <div key={group.scope} className="space-y-1">
            <div className="flex items-center gap-1.5 px-2">
              <span className="text-xs">{roleAvatar(group.scope)}</span>
              <span className="text-[10px] uppercase tracking-wider text-white/35 truncate">
                {roleName(group.scope)}
              </span>
            </div>
            {group.conversations.map((conversation) => {
              const active = conversation.id === currentSessionId;
              return (
                <button
                  key={conversation.id}
                  onClick={() => handleSelect(conversation.id)}
                  className={`w-full text-left px-2.5 py-2 rounded-lg transition-all flex items-start gap-2 group ${
                    active
                      ? 'bg-white/10 text-white border border-white/10'
                      : 'text-white/55 hover:bg-white/5 hover:text-white/85 border border-transparent'
                  }`}
                >
                  <MessageSquarePlus
                    size={12}
                    className={`mt-0.5 shrink-0 ${active ? 'text-emerald-400' : 'opacity-30'}`}
                  />
                  <span className="flex-1 min-w-0">
                    <span className="block text-xs truncate">
                      {conversationDisplayTitle(conversation.title, conversation.id)}
                    </span>
                    <span className="block text-[10px] text-white/25 mt-0.5">
                      {relativeTime(conversation.updated_at)}
                    </span>
                  </span>
                  {conversation.unread ? (
                    <span className="mt-1 w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)]" />
                  ) : null}
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
};

export default ConversationSidebar;
