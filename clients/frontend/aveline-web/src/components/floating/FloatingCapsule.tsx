import React, { useEffect, useRef, useState } from 'react';
import { GripVertical, Maximize2, Send, Sparkles, X } from 'lucide-react';

interface FloatingCapsuleProps {
  enabled: boolean;
  avatar?: string;
  lastMessage?: string;
  isTyping?: boolean;
  onSend: (text: string) => void;
  onOpenChat: () => void;
  onClose: () => void;
}

const POSITION_KEY = 'aveline_capsule_position_v1';

/**
 * 网页版悬浮助手胶囊。
 *
 * 系统级悬浮窗（跨 App 置顶）只有安卓能实现，网页只能在自身页面内浮层，
 * 因此这里做「页面内可拖拽胶囊」：收起时是一个小球，点开是迷你输入框，
 * 位置按浏览器保存，切到别的 Tab 仍然浮在聊天页上方。
 */
export const FloatingCapsule: React.FC<FloatingCapsuleProps> = ({
  enabled,
  avatar,
  lastMessage,
  isTyping,
  onSend,
  onOpenChat,
  onClose,
}) => {
  const [position, setPosition] = useState<{ x: number; y: number }>(() => {
    try {
      const raw = localStorage.getItem(POSITION_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (typeof parsed?.x === 'number' && typeof parsed?.y === 'number') return parsed;
      }
    } catch {
      // 忽略
    }
    return { x: window.innerWidth - 96, y: window.innerHeight - 140 };
  });
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const dragRef = useRef<{ dx: number; dy: number; moved: boolean } | null>(null);

  useEffect(() => {
    if (!enabled) setOpen(false);
  }, [enabled]);

  if (!enabled) return null;

  const persist = (next: { x: number; y: number }) => {
    setPosition(next);
    try {
      localStorage.setItem(POSITION_KEY, JSON.stringify(next));
    } catch {
      // 忽略
    }
  };

  const onPointerDown = (event: React.PointerEvent) => {
    (event.target as HTMLElement).setPointerCapture?.(event.pointerId);
    dragRef.current = {
      dx: event.clientX - position.x,
      dy: event.clientY - position.y,
      moved: false,
    };
  };

  const onPointerMove = (event: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    const nextX = Math.min(window.innerWidth - 64, Math.max(8, event.clientX - drag.dx));
    const nextY = Math.min(window.innerHeight - 64, Math.max(8, event.clientY - drag.dy));
    if (Math.abs(nextX - position.x) > 2 || Math.abs(nextY - position.y) > 2) drag.moved = true;
    persist({ x: nextX, y: nextY });
  };

  const onPointerUp = () => {
    const drag = dragRef.current;
    dragRef.current = null;
    if (drag && !drag.moved) setOpen((prev) => !prev);
  };

  const send = () => {
    const text = draft.trim();
    if (!text) return;
    onSend(text);
    setDraft('');
    setOpen(false);
  };

  return (
    <div
      className="fixed z-[80] select-none"
      style={{ left: position.x, top: position.y }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
    >
      {open ? (
        <div className="w-72 rounded-2xl border border-white/15 bg-[#0b0b12]/95 backdrop-blur-2xl shadow-2xl overflow-hidden">
          <div className="flex items-center gap-2 px-3 py-2 border-b border-white/5 cursor-grab">
            <GripVertical size={12} className="text-white/25" />
            <span className="text-[11px] text-white/70 flex-1 truncate">
              {avatar || '🪐'} 悬浮助手
            </span>
            <button
              onClick={(event) => {
                event.stopPropagation();
                onOpenChat();
              }}
              className="p-1 rounded text-white/35 hover:text-white hover:bg-white/10"
              title="回到聊天"
            >
              <Maximize2 size={11} />
            </button>
            <button
              onClick={(event) => {
                event.stopPropagation();
                onClose();
              }}
              className="p-1 rounded text-white/35 hover:text-white hover:bg-white/10"
              title="关闭胶囊"
            >
              <X size={11} />
            </button>
          </div>

          <div className="px-3 py-2 max-h-28 overflow-y-auto custom-scrollbar">
            <div className="text-[11px] text-white/45 leading-relaxed whitespace-pre-wrap">
              {isTyping ? '正在输入…' : lastMessage || '还没有消息'}
            </div>
          </div>

          <div className="flex items-center gap-1.5 px-2 py-2 border-t border-white/5">
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  send();
                }
              }}
              placeholder="直接说点什么…"
              className="flex-1 bg-black/40 border border-white/10 rounded-lg px-2.5 py-1.5 text-[11px] text-white outline-none focus:border-emerald-500/50"
            />
            <button
              onClick={send}
              disabled={!draft.trim()}
              className="p-1.5 rounded-lg bg-emerald-500/20 text-emerald-200 border border-emerald-500/25 disabled:opacity-30"
            >
              <Send size={12} />
            </button>
          </div>
        </div>
      ) : (
        <button
          className="w-12 h-12 rounded-full bg-gradient-to-br from-emerald-500/30 to-sky-500/30 border border-white/20 backdrop-blur-xl shadow-[0_8px_24px_rgba(0,0,0,0.5)] flex items-center justify-center text-lg hover:scale-105 active:scale-95 transition-transform cursor-grab"
          title="悬浮助手（拖动可移动）"
        >
          {avatar || <Sparkles size={16} className="text-white/80" />}
        </button>
      )}
    </div>
  );
};

export default FloatingCapsule;
