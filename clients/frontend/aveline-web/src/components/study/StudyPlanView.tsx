import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock,
  Play,
  Plus,
  RefreshCw,
} from 'lucide-react';
import { studyPlanApi, type DailyPlan, type PlanItem } from '../../api/extendedApi';
import { PlanItemDialog, type PlanItemDraft } from './PlanItemDialog';

function localDate(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function shiftDate(date: string, delta: number): string {
  const d = new Date(`${date}T00:00:00`);
  d.setDate(d.getDate() + delta);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function weekdayLabel(date: string): string {
  const d = new Date(`${date}T00:00:00`);
  if (Number.isNaN(d.getTime())) return '';
  return ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()];
}

export const StudyPlanView: React.FC<{ onStartFocus?: (subject: string, minutes: number) => void }> = ({
  onStartFocus,
}) => {
  const today = useMemo(() => localDate(0), []);
  const [date, setDate] = useState(today);
  const [plan, setPlan] = useState<DailyPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<PlanItem | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async (target: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await studyPlanApi.get(target);
      if (res?.status === 'error') {
        setError(res.message || '加载计划失败');
        setPlan(null);
      } else {
        const payload = res?.data ?? res;
        setPlan({
          date: payload?.date ?? target,
          items: Array.isArray(payload?.items) ? payload.items : [],
          daily_goal_minutes: payload?.daily_goal_minutes ?? 0,
          notes: payload?.notes ?? null,
          source: payload?.source,
          updated_at: payload?.updated_at,
        });
      }
    } catch (e: any) {
      setError(e?.message || '加载计划失败');
      setPlan(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(date);
  }, [date, load]);

  const items = plan?.items ?? [];
  const completed = items.filter((item) => item.status === 'completed').length;
  const plannedMinutes = items.reduce((sum, item) => sum + Number(item.estimated_duration_minutes || 0), 0);
  const goalMinutes = Number(plan?.daily_goal_minutes || 0);

  const toggle = async (item: PlanItem) => {
    const done = item.status !== 'completed';
    setBusyId(item.id);
    // 乐观更新，失败再回滚
    setPlan((prev) =>
      prev
        ? {
            ...prev,
            items: prev.items.map((it) =>
              it.id === item.id ? { ...it, status: done ? 'completed' : 'pending' } : it,
            ),
          }
        : prev,
    );
    try {
      const res = await studyPlanApi.setItemStatus({ date, item_id: item.id, done });
      if (res?.status === 'error') {
        setError(res.message || '更新状态失败');
        await load(date);
      }
    } catch (e: any) {
      setError(e?.message || '更新状态失败');
      await load(date);
    } finally {
      setBusyId(null);
    }
  };

  const submit = async (draft: PlanItemDraft) => {
    setSubmitting(true);
    try {
      const payload = {
        date,
        time: draft.time,
        title: draft.title.trim(),
        duration_minutes: draft.duration_minutes,
      };
      const res = editing
        ? await studyPlanApi.updateItem({ ...payload, item_id: editing.id })
        : await studyPlanApi.addItem(payload);
      if (res?.status === 'error') {
        setError(res.message || '保存失败');
      } else {
        setDialogOpen(false);
        setEditing(null);
        await load(date);
      }
    } catch (e: any) {
      setError(e?.message || '保存失败');
    } finally {
      setSubmitting(false);
    }
  };

  const remove = async () => {
    if (!editing) return;
    setSubmitting(true);
    try {
      const res = await studyPlanApi.removeItem({ date, item_id: editing.id });
      if (res?.status === 'error') {
        setError(res.message || '删除失败');
      } else {
        setDialogOpen(false);
        setEditing(null);
        await load(date);
      }
    } catch (e: any) {
      setError(e?.message || '删除失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="shrink-0 flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setDate((d) => shiftDate(d, -1))}
            className="p-1.5 rounded-lg bg-white/5 text-white/45 hover:text-white/85"
          >
            <ChevronLeft size={14} />
          </button>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5 border border-white/10">
            <CalendarDays size={13} className="text-emerald-300" />
            <span className="text-xs text-white/85 tabular-nums">{date}</span>
            <span className="text-[10px] text-white/30">{weekdayLabel(date)}</span>
          </div>
          <button
            onClick={() => setDate((d) => shiftDate(d, 1))}
            className="p-1.5 rounded-lg bg-white/5 text-white/45 hover:text-white/85"
          >
            <ChevronRight size={14} />
          </button>
          {date !== today && (
            <button
              onClick={() => setDate(today)}
              className="px-2.5 py-1 rounded-lg bg-white/5 text-[11px] text-white/45 hover:text-white/80"
            >
              今天
            </button>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => void load(date)}
            disabled={loading}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-white/5 text-[11px] text-white/45 hover:text-white/80 disabled:opacity-40"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            刷新
          </button>
          <button
            onClick={() => {
              setEditing(null);
              setDialogOpen(true);
            }}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-500/15 border border-emerald-500/25 text-[11px] text-emerald-200 hover:bg-emerald-500/25"
          >
            <Plus size={12} />
            新增
          </button>
        </div>
      </div>

      <div className="shrink-0 grid grid-cols-3 gap-2 mb-3">
        <div className="rounded-xl bg-white/5 border border-white/5 px-3 py-2">
          <div className="text-[10px] text-white/30">完成</div>
          <div className="text-sm text-emerald-300 tabular-nums">
            {completed}/{items.length}
          </div>
        </div>
        <div className="rounded-xl bg-white/5 border border-white/5 px-3 py-2">
          <div className="text-[10px] text-white/30">计划时长</div>
          <div className="text-sm text-white/80 tabular-nums">{plannedMinutes} 分</div>
        </div>
        <div className="rounded-xl bg-white/5 border border-white/5 px-3 py-2">
          <div className="text-[10px] text-white/30">日目标</div>
          <div className="text-sm text-sky-300 tabular-nums">{goalMinutes > 0 ? `${goalMinutes} 分` : '--'}</div>
        </div>
      </div>

      {error && (
        <div className="shrink-0 mb-2 flex items-start gap-1.5 rounded-xl border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-200">
          <AlertCircle size={12} className="mt-0.5 shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={() => setError(null)} className="text-rose-200/60 hover:text-rose-100">
            关闭
          </button>
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar space-y-2 pr-0.5">
        {loading && items.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-14">
            <div className="w-8 h-8 border-2 border-emerald-400/20 border-t-emerald-400 rounded-full animate-spin" />
            <div className="text-xs text-white/35">加载计划…</div>
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-14 text-center">
            <CalendarDays size={34} className="text-white/10" />
            <div className="text-sm text-white/50">这一天还没有计划</div>
            <div className="text-[11px] text-white/25">新增一项，或让 AI 在聊天里帮你排计划</div>
          </div>
        ) : (
          items.map((item) => {
            const done = item.status === 'completed';
            return (
              <div
                key={item.id}
                className={`group rounded-xl border px-3 py-2.5 transition-colors ${
                  done
                    ? 'border-emerald-500/15 bg-emerald-500/5'
                    : 'border-white/8 bg-white/5 hover:border-white/15'
                }`}
              >
                <div className="flex items-start gap-3">
                  <button
                    onClick={() => void toggle(item)}
                    disabled={busyId === item.id}
                    className={`mt-0.5 w-5 h-5 rounded-md border flex items-center justify-center shrink-0 transition-colors ${
                      done
                        ? 'bg-emerald-500/25 border-emerald-400/40 text-emerald-200'
                        : 'border-white/20 text-transparent hover:border-white/40'
                    }`}
                    title={done ? '标记未完成' : '标记完成'}
                  >
                    <Check size={12} />
                  </button>

                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 min-w-0">
                      <span
                        className={`text-sm truncate ${done ? 'text-white/35 line-through' : 'text-white/85'}`}
                      >
                        {item.title}
                      </span>
                      {item.priority === 'high' && (
                        <span className="shrink-0 px-1.5 py-0.5 rounded text-[9px] bg-rose-500/15 text-rose-300 border border-rose-500/20">
                          高优先
                        </span>
                      )}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-white/30">
                      {item.time && (
                        <span className="flex items-center gap-1 tabular-nums">
                          <Clock size={10} />
                          {item.time}
                        </span>
                      )}
                      <span className="tabular-nums">
                        {Number(item.estimated_duration_minutes || 0)} 分钟
                      </span>
                      {item.subject && <span>{item.subject}</span>}
                      {Number(item.actual_minutes || 0) > 0 && (
                        <span className="text-emerald-300/70">
                          已学 {Math.round(Number(item.actual_minutes))} 分
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="shrink-0 flex items-center gap-1 opacity-70 group-hover:opacity-100">
                    {onStartFocus && (
                      <button
                        onClick={() =>
                          onStartFocus(item.title, Number(item.estimated_duration_minutes || 25) || 25)
                        }
                        className="p-1.5 rounded-lg bg-white/5 text-white/40 hover:text-emerald-300"
                        title="开始专注"
                      >
                        <Play size={12} />
                      </button>
                    )}
                    <button
                      onClick={() => {
                        setEditing(item);
                        setDialogOpen(true);
                      }}
                      className="px-2 py-1 rounded-lg bg-white/5 text-[10px] text-white/40 hover:text-white/85"
                    >
                      编辑
                    </button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      <PlanItemDialog
        open={dialogOpen}
        editing={editing}
        submitting={submitting}
        onClose={() => {
          setDialogOpen(false);
          setEditing(null);
        }}
        onSubmit={(draft) => void submit(draft)}
        onDelete={() => void remove()}
      />
    </div>
  );
};

export default StudyPlanView;
