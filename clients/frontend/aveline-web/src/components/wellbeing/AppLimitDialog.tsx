import React, { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import type { AppLimit } from '../../api/extendedApi';
import { minutesToMs, msToMinutes } from '../../utils/duration';

export interface AppLimitDraft {
  package_name: string;
  app_name: string;
  daily_minutes: number;
  session_minutes: number;
  cooldown_minutes: number;
  gap_minutes: number;
}

const EMPTY: AppLimitDraft = {
  package_name: '',
  app_name: '',
  daily_minutes: 60,
  session_minutes: 0,
  cooldown_minutes: 5,
  gap_minutes: 5,
};

function fromLimit(limit: AppLimit): AppLimitDraft {
  return {
    package_name: limit.package_name,
    app_name: limit.app_name || '',
    daily_minutes: msToMinutes(limit.limit_ms),
    session_minutes: msToMinutes(limit.session_limit_ms),
    cooldown_minutes: msToMinutes(limit.cooldown_ms),
    gap_minutes: msToMinutes(limit.session_gap_ms),
  };
}

export const AppLimitDialog: React.FC<{
  open: boolean;
  editing: AppLimit | null;
  knownPackages: string[];
  submitting: boolean;
  onClose: () => void;
  onSubmit: (draft: AppLimitDraft) => void;
}> = ({ open, editing, knownPackages, submitting, onClose, onSubmit }) => {
  const [draft, setDraft] = useState<AppLimitDraft>(EMPTY);

  useEffect(() => {
    if (!open) return;
    setDraft(editing ? fromLimit(editing) : EMPTY);
  }, [open, editing]);

  if (!open) return null;

  const patch = (key: keyof AppLimitDraft, value: string | number) =>
    setDraft((prev) => ({ ...prev, [key]: value }));

  const valid = draft.package_name.trim().length > 0 && draft.daily_minutes >= 0;

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-md rounded-2xl border border-white/10 bg-zinc-950/95 shadow-2xl">
        <header className="flex items-center justify-between px-5 py-4 border-b border-white/5">
          <div>
            <h3 className="text-sm font-semibold text-white/90">{editing ? '编辑应用限额' : '添加应用限额'}</h3>
            <p className="text-[11px] text-white/35 mt-0.5">
              限额由后端保存，安卓端无障碍服务负责实时拦截
            </p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-full bg-white/5 text-white/40 hover:text-white/70">
            <X size={14} />
          </button>
        </header>

        <div className="p-5 space-y-3">
          <label className="block">
            <span className="text-[10px] uppercase tracking-wider text-white/30">包名 *</span>
            <input
              value={draft.package_name}
              onChange={(e) => patch('package_name', e.target.value.trim())}
              placeholder="com.example.app"
              disabled={!!editing}
              className="mt-1 w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-white/85 outline-none focus:border-emerald-400/40 disabled:opacity-50"
            />
            {knownPackages.length > 0 && !editing && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {knownPackages.slice(0, 6).map((pkg) => (
                  <button
                    key={pkg}
                    onClick={() => patch('package_name', pkg)}
                    className="px-2 py-0.5 rounded-full bg-white/5 text-[10px] text-white/45 hover:text-white/80"
                  >
                    {pkg}
                  </button>
                ))}
              </div>
            )}
          </label>

          <label className="block">
            <span className="text-[10px] uppercase tracking-wider text-white/30">应用名称</span>
            <input
              value={draft.app_name}
              onChange={(e) => patch('app_name', e.target.value)}
              placeholder="留空则使用包名"
              className="mt-1 w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-white/85 outline-none focus:border-emerald-400/40"
            />
          </label>

          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="text-[10px] uppercase tracking-wider text-white/30">每日限额（分钟）</span>
              <input
                type="number"
                min={0}
                value={draft.daily_minutes}
                onChange={(e) => patch('daily_minutes', Number(e.target.value))}
                className="mt-1 w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-white/85 outline-none focus:border-emerald-400/40"
              />
            </label>
            <label className="block">
              <span className="text-[10px] uppercase tracking-wider text-white/30">单次限额（分钟）</span>
              <input
                type="number"
                min={0}
                value={draft.session_minutes}
                onChange={(e) => patch('session_minutes', Number(e.target.value))}
                className="mt-1 w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-white/85 outline-none focus:border-emerald-400/40"
              />
            </label>
            <label className="block">
              <span className="text-[10px] uppercase tracking-wider text-white/30">超时休息（分钟）</span>
              <input
                type="number"
                min={0}
                value={draft.cooldown_minutes}
                onChange={(e) => patch('cooldown_minutes', Number(e.target.value))}
                className="mt-1 w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-white/85 outline-none focus:border-emerald-400/40"
              />
            </label>
            <label className="block">
              <span className="text-[10px] uppercase tracking-wider text-white/30">离开多久算结束（分钟）</span>
              <input
                type="number"
                min={0}
                value={draft.gap_minutes}
                onChange={(e) => patch('gap_minutes', Number(e.target.value))}
                className="mt-1 w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-white/85 outline-none focus:border-emerald-400/40"
              />
            </label>
          </div>

          <p className="text-[10px] text-white/25 leading-relaxed">
            每日限额填 0 表示不做每日限制；单次限额填 0 表示不限制单次连续使用。
          </p>
        </div>

        <footer className="flex items-center justify-end gap-2 px-5 py-3 border-t border-white/5">
          <button onClick={onClose} className="px-4 py-2 text-xs text-white/45 hover:text-white/80">
            取消
          </button>
          <button
            disabled={!valid || submitting}
            onClick={() => onSubmit(draft)}
            className="px-4 py-2 rounded-xl bg-emerald-500/15 border border-emerald-500/25 text-xs text-emerald-200 hover:bg-emerald-500/25 transition-colors disabled:opacity-40"
          >
            {submitting ? '保存中…' : '保存'}
          </button>
        </footer>
      </div>
    </div>
  );
};

export function draftToPayload(draft: AppLimitDraft) {
  return {
    package_name: draft.package_name.trim(),
    app_name: draft.app_name.trim(),
    limit_ms: minutesToMs(draft.daily_minutes),
    session_limit_ms: minutesToMs(draft.session_minutes),
    cooldown_ms: minutesToMs(draft.cooldown_minutes),
    session_gap_ms: minutesToMs(draft.gap_minutes),
  };
}
