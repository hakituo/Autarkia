import React, { useEffect, useState } from 'react';
import { BookOpen, Check, Clock, Moon, Pencil, X } from 'lucide-react';
import { dailyApi } from '../../api/extendedApi';
import { LifeEmpty, LifeSection, Pill, StatGrid, StatTile } from './LifeUi';
import { formatClock, formatMinutes, type LifePortrait } from './types';

const TIME_RE = /^([01]\d|2[0-3]):([0-5]\d)$/;

/** 用 HH:mm 计算跨夜时长（分钟）。 */
function durationMinutes(sleep?: string | null, wakeup?: string | null): number | null {
  if (!sleep || !wakeup || !TIME_RE.test(sleep) || !TIME_RE.test(wakeup)) return null;
  const [sh, sm] = sleep.split(':').map(Number);
  const [wh, wm] = wakeup.split(':').map(Number);
  let diff = wh * 60 + wm - (sh * 60 + sm);
  if (diff <= 0) diff += 24 * 60;
  return diff;
}

export const LifeScheduleTab: React.FC<{ portrait: LifePortrait | null; onSaved: () => void }> = ({
  portrait,
  onSaved,
}) => {
  const wakeup = portrait?.schedule?.wakeup || '';
  const sleep = portrait?.schedule?.sleep || '';
  const [editing, setEditing] = useState(false);
  const [draftWakeup, setDraftWakeup] = useState(wakeup);
  const [draftSleep, setDraftSleep] = useState(sleep);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);

  useEffect(() => {
    setDraftWakeup(wakeup);
    setDraftSleep(sleep);
  }, [wakeup, sleep]);

  const duration = durationMinutes(sleep, wakeup);
  const study = portrait?.study;
  const mode = portrait?.mode;

  const save = async () => {
    if (!TIME_RE.test(draftWakeup) || !TIME_RE.test(draftSleep)) {
      setMessage({ text: '时间格式应为 HH:mm', ok: false });
      return;
    }
    setSaving(true);
    try {
      const res = await dailyApi.recordSchedule({ wakeup: draftWakeup, sleep: draftSleep });
      if ((res?.status ?? 'success') === 'success') {
        setMessage({ text: res?.message || '作息已保存', ok: true });
        setEditing(false);
        onSaved();
      } else {
        setMessage({ text: res?.message || '保存失败', ok: false });
      }
    } catch (e: any) {
      setMessage({ text: e?.message || '保存失败', ok: false });
    } finally {
      setSaving(false);
      window.setTimeout(() => setMessage(null), 3000);
    }
  };

  return (
    <div className="space-y-3">
      <LifeSection
        title="今日作息"
        icon={<Moon size={16} />}
        subtitle="入睡 / 起床"
        action={
          editing ? (
            <div className="flex items-center gap-1">
              <button
                onClick={() => void save()}
                disabled={saving}
                className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-emerald-500/15 border border-emerald-500/25 text-[11px] text-emerald-200 disabled:opacity-40"
              >
                <Check size={11} />
                保存
              </button>
              <button
                onClick={() => {
                  setEditing(false);
                  setDraftWakeup(wakeup);
                  setDraftSleep(sleep);
                }}
                className="p-1.5 rounded-full bg-white/5 text-white/40 hover:text-white/70"
              >
                <X size={11} />
              </button>
            </div>
          ) : (
            <button
              onClick={() => setEditing(true)}
              className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-white/5 border border-white/10 text-[11px] text-white/60 hover:bg-white/10"
            >
              <Pencil size={11} />
              编辑作息
            </button>
          )
        }
      >
        {editing ? (
          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="text-[10px] uppercase tracking-wider text-white/30">睡觉时间</span>
              <input
                type="time"
                value={draftSleep}
                onChange={(e) => setDraftSleep(e.target.value)}
                className="mt-1 w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-white/85 outline-none focus:border-emerald-400/40"
              />
            </label>
            <label className="block">
              <span className="text-[10px] uppercase tracking-wider text-white/30">起床时间</span>
              <input
                type="time"
                value={draftWakeup}
                onChange={(e) => setDraftWakeup(e.target.value)}
                className="mt-1 w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-white/85 outline-none focus:border-emerald-400/40"
              />
            </label>
          </div>
        ) : (
          <StatGrid>
            <StatTile label="入睡" value={formatClock(sleep)} tone="sky" />
            <StatTile label="起床" value={formatClock(wakeup)} tone="amber" />
            <StatTile label="在床时长" value={formatMinutes(duration)} />
          </StatGrid>
        )}
        {message && (
          <div className={`mt-2 text-[11px] ${message.ok ? 'text-emerald-300' : 'text-rose-300'}`}>
            {message.text}
          </div>
        )}
      </LifeSection>

      {mode?.reduced_mode_active && (
        <LifeSection title="低打扰模式" icon={<Clock size={16} />} subtitle="主动关怀已降频">
          <div className="flex items-center justify-between gap-3">
            <div className="text-xs text-white/50">
              {mode.reduced_mode_reason && mode.reduced_mode_reason !== 'none'
                ? `原因：${mode.reduced_mode_reason}`
                : '当前处于低打扰状态'}
            </div>
            {mode.reduced_mode_expected_end_ts ? (
              <Pill tone="amber">
                预计{' '}
                {(() => {
                  const end = new Date(mode.reduced_mode_expected_end_ts * 1000);
                  return `${String(end.getHours()).padStart(2, '0')}:${String(end.getMinutes()).padStart(2, '0')}`;
                })()}{' '}
                结束
              </Pill>
            ) : null}
          </div>
        </LifeSection>
      )}

      <LifeSection
        title="今日学习"
        icon={<BookOpen size={16} />}
        subtitle="来自学习会话与手动记录"
        action={<Pill tone="emerald">{formatMinutes(study?.total_minutes)}</Pill>}
      >
        {!study?.sessions?.length ? (
          <LifeEmpty icon={<BookOpen size={30} />} title="今天还没有学习会话" hint="可在「学习」模块开始一次专注。" />
        ) : (
          <div className="space-y-2">
            <StatGrid columns="grid-cols-2">
              <StatTile label="总时长" value={formatMinutes(study?.total_minutes)} tone="emerald" />
              <StatTile label="会话数" value={study?.count ?? study.sessions.length} unit="次" />
            </StatGrid>
            <ul className="divide-y divide-white/5">
              {study.sessions
                .slice()
                .reverse()
                .map((session, index) => (
                  <li key={`${session.time}-${index}`} className="flex items-start justify-between gap-3 py-2">
                    <div className="min-w-0">
                      <div className="text-xs text-white/75 truncate">{session.topic || '学习'}</div>
                      {session.content && (
                        <div className="text-[10px] text-white/30 truncate">{session.content}</div>
                      )}
                    </div>
                    <span className="text-[10px] text-white/30 tabular-nums shrink-0">
                      {formatClock(session.time)}
                    </span>
                  </li>
                ))}
            </ul>
          </div>
        )}
      </LifeSection>
    </div>
  );
};
