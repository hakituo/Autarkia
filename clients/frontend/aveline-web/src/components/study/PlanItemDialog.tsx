import React, { useEffect, useState } from 'react';
import { Trash2, X } from 'lucide-react';
import type { PlanItem } from '../../api/extendedApi';

export interface PlanItemDraft {
  time: string;
  title: string;
  duration_minutes: number;
}

const EMPTY: PlanItemDraft = { time: '', title: '', duration_minutes: 60 };

const TIME_RE = /^([01]\d|2[0-3]):([0-5]\d)$/;

export const PlanItemDialog: React.FC<{
  open: boolean;
  editing: PlanItem | null;
  submitting: boolean;
  onClose: () => void;
  onSubmit: (draft: PlanItemDraft) => void;
  onDelete?: () => void;
}> = ({ open, editing, submitting, onClose, onSubmit, onDelete }) => {
  const [draft, setDraft] = useState<PlanItemDraft>(EMPTY);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    if (!open) return;
    setTouched(false);
    setDraft(
      editing
        ? {
            time: (editing.time || '').slice(0, 5),
            title: editing.title || '',
            duration_minutes: Number(editing.estimated_duration_minutes || 60),
          }
        : EMPTY,
    );
  }, [open, editing]);

  if (!open) return null;

  const timeValid = draft.time === '' || TIME_RE.test(draft.time);
  const valid = draft.title.trim().length > 0 && timeValid && draft.duration_minutes > 0;

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-md rounded-2xl border border-white/10 bg-zinc-950/95 shadow-2xl">
        <header className="flex items-center justify-between px-5 py-4 border-b border-white/5">
          <div>
            <h3 className="text-sm font-semibold text-white/90">{editing ? '编辑计划项' : '新增计划项'}</h3>
            <p className="text-[11px] text-white/35 mt-0.5">计划由后端持久化，与安卓端共用同一份</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-full bg-white/5 text-white/40 hover:text-white/70">
            <X size={14} />
          </button>
        </header>

        <div className="p-5 space-y-3">
          <label className="block">
            <span className="text-[10px] uppercase tracking-wider text-white/30">名称 *</span>
            <input
              value={draft.title}
              onChange={(e) => setDraft((prev) => ({ ...prev, title: e.target.value }))}
              onBlur={() => setTouched(true)}
              placeholder="例如：英语阅读 30 分钟"
              className="mt-1 w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-white/85 outline-none focus:border-emerald-400/40"
            />
          </label>

          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="text-[10px] uppercase tracking-wider text-white/30">时间（可空）</span>
              <input
                type="time"
                value={draft.time}
                onChange={(e) => setDraft((prev) => ({ ...prev, time: e.target.value }))}
                className="mt-1 w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-white/85 outline-none focus:border-emerald-400/40"
              />
            </label>
            <label className="block">
              <span className="text-[10px] uppercase tracking-wider text-white/30">预计时长（分钟）</span>
              <input
                type="number"
                min={1}
                max={720}
                value={draft.duration_minutes}
                onChange={(e) =>
                  setDraft((prev) => ({ ...prev, duration_minutes: Number(e.target.value) }))
                }
                className="mt-1 w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-white/85 outline-none focus:border-emerald-400/40"
              />
            </label>
          </div>

          {touched && !valid && (
            <p className="text-[11px] text-rose-300">
              {draft.title.trim().length === 0 ? '名称不能为空' : '请检查时间与时长'}
            </p>
          )}
        </div>

        <footer className="flex items-center justify-between gap-2 px-5 py-3 border-t border-white/5">
          <div>
            {editing && onDelete && (
              <button
                onClick={onDelete}
                className="flex items-center gap-1 px-3 py-2 rounded-xl bg-rose-500/10 border border-rose-500/20 text-[11px] text-rose-200 hover:bg-rose-500/20"
              >
                <Trash2 size={12} />
                删除
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onClose} className="px-4 py-2 text-xs text-white/45 hover:text-white/80">
              取消
            </button>
            <button
              disabled={!valid || submitting}
              onClick={() => onSubmit(draft)}
              className="px-4 py-2 rounded-xl bg-emerald-500/15 border border-emerald-500/25 text-xs text-emerald-200 hover:bg-emerald-500/25 disabled:opacity-40"
            >
              {submitting ? '保存中…' : '保存'}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
};
