import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Bell, BellOff, CheckCheck, RefreshCw, X } from 'lucide-react';
import { useFeatureStore } from '../../store/useFeatureStore';
import { relativeTime } from '../../utils/conversation';

interface NotificationCenterProps {
  onNavigate?: (payload: Record<string, unknown>) => void;
}

const TYPE_STYLES: Record<string, string> = {
  vocabulary: 'text-sky-300 bg-sky-500/10 border-sky-500/20',
  image: 'text-purple-300 bg-purple-500/10 border-purple-500/20',
  voice: 'text-amber-300 bg-amber-500/10 border-amber-500/20',
  text: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20',
};

/** 通知中心：顶栏铃铛 + 未读徽章 + 列表。数据源 /api/v1/notifications。 */
export const NotificationCenter: React.FC<NotificationCenterProps> = ({ onNavigate }) => {
  const [open, setOpen] = useState(false);
  const [onlyUnread, setOnlyUnread] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  const notifications = useFeatureStore((s) => s.notifications);
  const unread = useFeatureStore((s) => s.unreadNotifications);
  const loading = useFeatureStore((s) => s.notificationsLoading);
  const loadNotifications = useFeatureStore((s) => s.loadNotifications);
  const markNotificationsRead = useFeatureStore((s) => s.markNotificationsRead);

  useEffect(() => {
    void loadNotifications();
    const timer = window.setInterval(() => void loadNotifications(), 30000);
    return () => window.clearInterval(timer);
  }, [loadNotifications]);

  useEffect(() => {
    if (!open) return;
    const handler = (event: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener('mousedown', handler);
    return () => window.removeEventListener('mousedown', handler);
  }, [open]);

  const visible = useMemo(
    () => (onlyUnread ? notifications.filter((item) => !item.read) : notifications),
    [notifications, onlyUnread],
  );

  const handleItemClick = (id: string, read: boolean, payload?: Record<string, unknown>) => {
    if (!read) void markNotificationsRead([id]);
    if (payload && onNavigate) onNavigate(payload);
    setOpen(false);
  };

  return (
    <div className="relative" ref={panelRef}>
      <button
        onClick={() => {
          setOpen((prev) => !prev);
          if (!open) void loadNotifications();
        }}
        className="relative w-9 h-9 rounded-full bg-white/5 border border-white/10 flex items-center justify-center hover:bg-white/10 transition-colors"
        title="通知中心"
      >
        <Bell size={16} className={unread > 0 ? 'text-amber-300' : 'text-white/50'} />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[15px] h-[15px] px-1 rounded-full bg-amber-400 text-[9px] font-bold text-black flex items-center justify-center">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-11 w-[360px] max-h-[70vh] rounded-2xl border border-white/10 bg-[#0b0b12]/95 backdrop-blur-2xl shadow-2xl overflow-hidden z-50 flex flex-col">
          <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
            <div className="flex items-center gap-2">
              <span className="text-xs text-white/80">通知</span>
              <span className="text-[10px] font-mono text-white/30">{notifications.length}</span>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => void loadNotifications()}
                className="p-1.5 rounded-lg text-white/35 hover:text-white hover:bg-white/10 transition-colors"
                title="刷新"
              >
                <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
              </button>
              <button
                onClick={() => void markNotificationsRead()}
                disabled={unread === 0}
                className="p-1.5 rounded-lg text-white/35 hover:text-emerald-300 hover:bg-emerald-500/10 transition-colors disabled:opacity-30"
                title="全部已读"
              >
                <CheckCheck size={12} />
              </button>
              <button
                onClick={() => setOpen(false)}
                className="p-1.5 rounded-lg text-white/35 hover:text-white hover:bg-white/10 transition-colors"
              >
                <X size={12} />
              </button>
            </div>
          </div>

          <div className="px-3 py-2 border-b border-white/5 flex items-center gap-2">
            <button
              onClick={() => setOnlyUnread(false)}
              className={`px-2 py-1 rounded-md text-[10px] transition-colors ${
                onlyUnread ? 'text-white/40' : 'bg-white/10 text-white'
              }`}
            >
              全部
            </button>
            <button
              onClick={() => setOnlyUnread(true)}
              className={`px-2 py-1 rounded-md text-[10px] transition-colors ${
                onlyUnread ? 'bg-white/10 text-white' : 'text-white/40'
              }`}
            >
              未读 {unread > 0 ? `(${unread})` : ''}
            </button>
          </div>

          <div className="flex-1 overflow-y-auto custom-scrollbar">
            {visible.length === 0 && (
              <div className="flex flex-col items-center justify-center py-12 text-white/25 gap-2">
                <BellOff size={20} />
                <span className="text-[11px]">{onlyUnread ? '没有未读通知' : '暂无通知'}</span>
              </div>
            )}

            {visible.map((item) => (
              <button
                key={item.id}
                onClick={() =>
                  handleItemClick(item.id, item.read, item.payload as Record<string, unknown>)
                }
                className={`w-full text-left px-4 py-3 border-b border-white/5 transition-colors hover:bg-white/5 ${
                  item.read ? 'opacity-55' : ''
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`text-[9px] px-1.5 py-0.5 rounded border uppercase tracking-wider ${
                      TYPE_STYLES[item.type] || TYPE_STYLES.text
                    }`}
                  >
                    {item.type}
                  </span>
                  <span className="text-xs text-white/80 truncate flex-1">
                    {item.title || '通知'}
                  </span>
                  {!item.read && <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />}
                </div>
                <div className="text-[11px] text-white/45 line-clamp-2 whitespace-pre-wrap">
                  {item.content}
                </div>
                <div className="text-[10px] text-white/25 mt-1 font-mono">
                  {relativeTime(item.timestamp)}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default NotificationCenter;
