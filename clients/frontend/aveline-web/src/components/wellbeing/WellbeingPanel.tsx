import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  Hourglass,
  MonitorSmartphone,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import { wellbeingApi, type AppLimit } from '../../api/extendedApi';
import { clampRatio, formatDuration, formatDurationShort } from '../../utils/duration';
import { AppLimitDialog, draftToPayload, type AppLimitDraft } from './AppLimitDialog';

type StatusChip = { label: string; tone: 'emerald' | 'amber' | 'rose' | 'default' };

function statusOf(limit: AppLimit): StatusChip {
  const daily = limit.limit_ms || 0;
  const session = limit.session_limit_ms || 0;
  const used = limit.usage_today_ms || 0;
  if (daily <= 0 && session <= 0) return { label: '未设限额', tone: 'default' };
  if (session > 0 && used >= session && daily <= 0) return { label: '本次时间到', tone: 'amber' };
  if (daily > 0 && used >= daily) return { label: '今日已用完', tone: 'rose' };
  if (daily > 0 && used / daily >= 0.8) return { label: '接近上限', tone: 'amber' };
  return { label: '进行中', tone: 'emerald' };
}

const TONE_CLASS: Record<StatusChip['tone'], string> = {
  emerald: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
  amber: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
  rose: 'bg-rose-500/10 text-rose-300 border-rose-500/20',
  default: 'bg-white/5 text-white/45 border-white/10',
};

const BAR_CLASS: Record<StatusChip['tone'], string> = {
  emerald: 'bg-emerald-400',
  amber: 'bg-amber-400',
  rose: 'bg-rose-400',
  default: 'bg-white/30',
};

/** 后端 set/delete 不传 target_date 会默认写「明天」，前端必须显式传今天。 */
function todayDate(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/**
 * 数字健康：应用使用时长限额。
 *
 * 网页端负责「配置 + 查看用量」，真正的实时拦截在安卓端（无障碍 + UsageStats），
 * 所以这里不展示「授权就绪」卡片，只提示生效位置。
 */
export const WellbeingPanel: React.FC = () => {
  const [limits, setLimits] = useState<AppLimit[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<AppLimit | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<{ text: string; ok: boolean } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await wellbeingApi.limits();
      if (res?.status === 'error') {
        setError(res.message || '加载应用限额失败');
        setLimits([]);
      } else {
        setLimits(Array.isArray(res?.limits) ? res.limits : []);
      }
    } catch (e: any) {
      setError(e?.message || '加载应用限额失败，请检查后端连接');
      setLimits([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const knownPackages = useMemo(() => limits.map((item) => item.package_name), [limits]);

  const submit = async (draft: AppLimitDraft) => {
    setSubmitting(true);
    try {
      const res = await wellbeingApi.setLimit({ ...draftToPayload(draft), target_date: todayDate() });
      if (res?.status === 'error') {
        setNotice({ text: res.message || '保存失败', ok: false });
      } else {
        setNotice({ text: res?.message || '限额已保存', ok: true });
        setDialogOpen(false);
        setEditing(null);
        await load();
      }
    } catch (e: any) {
      setNotice({ text: e?.message || '保存失败', ok: false });
    } finally {
      setSubmitting(false);
      window.setTimeout(() => setNotice(null), 3000);
    }
  };

  const remove = async (limit: AppLimit) => {
    const ok = window.confirm(`确定移除「${limit.app_name || limit.package_name}」的限额吗？`);
    if (!ok) return;
    try {
      const res = await wellbeingApi.removeLimit(limit.package_name, todayDate());
      if (res?.status === 'error') {
        setNotice({ text: res.message || '移除失败', ok: false });
      } else {
        setNotice({ text: '限额已移除', ok: true });
        await load();
      }
    } catch (e: any) {
      setNotice({ text: e?.message || '移除失败', ok: false });
    } finally {
      window.setTimeout(() => setNotice(null), 3000);
    }
  };

  return (
    <div className="flex flex-col h-full p-4 md:p-6 overflow-hidden">
      <div className="shrink-0 flex items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center shrink-0">
            <ShieldCheck className="text-emerald-300" size={18} />
          </div>
          <div className="min-w-0">
            <h2 className="text-lg md:text-xl font-semibold text-white/95 tracking-wide">Wellbeing</h2>
            <p className="text-[10px] md:text-xs text-white/40 truncate">数字健康 · 应用使用时长限额</p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => void load()}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white/5 border border-white/10 text-[11px] text-white/55 hover:bg-white/10 disabled:opacity-40"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            刷新
          </button>
          <button
            onClick={() => {
              setEditing(null);
              setDialogOpen(true);
            }}
            className="flex items-center gap-1 px-3 py-1.5 rounded-full bg-emerald-500/15 border border-emerald-500/25 text-[11px] text-emerald-200 hover:bg-emerald-500/25"
          >
            <Plus size={12} />
            添加限额
          </button>
        </div>
      </div>

      {notice && (
        <div
          className={`shrink-0 mb-3 flex items-center gap-1.5 rounded-xl px-3 py-2 text-[11px] ${
            notice.ok
              ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-200'
              : 'bg-rose-500/10 border border-rose-500/20 text-rose-200'
          }`}
        >
          {notice.ok ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
          {notice.text}
        </div>
      )}

      <div className="shrink-0 mb-3 rounded-xl border border-white/5 bg-white/5 px-3 py-2 text-[11px] text-white/35 leading-relaxed">
        限额配置保存在后端，由安卓端无障碍服务实时拦截；网页端只负责设置与查看今日用量。
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar space-y-2.5">
        {loading && limits.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-16">
            <div className="w-8 h-8 border-2 border-emerald-400/20 border-t-emerald-400 rounded-full animate-spin" />
            <div className="text-xs text-white/35">加载限额…</div>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
            <AlertCircle size={34} className="text-rose-400/60" />
            <div className="text-sm text-white/55">{error}</div>
            <button onClick={() => void load()} className="text-[11px] text-emerald-300 hover:underline">
              重试
            </button>
          </div>
        ) : limits.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
            <MonitorSmartphone size={38} className="text-white/10" />
            <div className="text-sm text-white/50">还没有设置任何应用限额</div>
            <div className="text-[11px] text-white/25 max-w-sm">
              添加后，安卓端会在使用超限时提醒并拦截。也可以先在安卓端「数字健康」页设置。
            </div>
            <button
              onClick={() => {
                setEditing(null);
                setDialogOpen(true);
              }}
              className="mt-2 px-4 py-1.5 rounded-full bg-emerald-500/15 border border-emerald-500/25 text-[11px] text-emerald-200"
            >
              添加限额
            </button>
          </div>
        ) : (
          limits.map((limit) => {
            const status = statusOf(limit);
            const usedRatio = limit.limit_ms > 0 ? limit.usage_today_ms / limit.limit_ms : 0;
            const sessionRatio =
              limit.session_limit_ms > 0 ? limit.usage_today_ms / limit.session_limit_ms : 0;
            return (
              <div
                key={limit.package_name}
                className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 hover:border-white/15 transition-colors"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-sm font-medium text-white/90 truncate">
                        {limit.app_name || limit.package_name}
                      </span>
                      <span
                        className={`shrink-0 px-2 py-0.5 rounded-full text-[10px] border ${TONE_CLASS[status.tone]}`}
                      >
                        {status.label}
                      </span>
                    </div>
                    <div className="text-[10px] text-white/25 font-mono truncate mt-0.5">
                      {limit.package_name}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => {
                        setEditing(limit);
                        setDialogOpen(true);
                      }}
                      className="px-2.5 py-1 rounded-full bg-white/5 text-[10px] text-white/50 hover:text-white/85"
                    >
                      编辑
                    </button>
                    <button
                      onClick={() => void remove(limit)}
                      className="p-1.5 rounded-full bg-white/5 text-white/35 hover:text-rose-300"
                      title="移除限额"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>

                <div className="mt-2.5 space-y-2">
                  <div>
                    <div className="flex items-center justify-between text-[10px] text-white/35 mb-1">
                      <span>今日使用</span>
                      <span className="tabular-nums">
                        {formatDurationShort(limit.usage_today_ms)} /{' '}
                        {limit.limit_ms > 0 ? formatDurationShort(limit.limit_ms) : '无限制'}
                      </span>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-white/8 overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${BAR_CLASS[status.tone]}`}
                        style={{ width: `${clampRatio(usedRatio) * 100}%` }}
                      />
                    </div>
                  </div>
                  <div>
                    <div className="flex items-center justify-between text-[10px] text-white/35 mb-1">
                      <span>单次使用</span>
                      <span className="tabular-nums">
                        {limit.session_limit_ms > 0 ? formatDuration(limit.session_limit_ms) : '不限单次'}
                      </span>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-white/8 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-sky-400/80 transition-all"
                        style={{ width: `${clampRatio(sessionRatio) * 100}%` }}
                      />
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-white/25">
                    <span className="flex items-center gap-1">
                      <Hourglass size={10} />
                      超时休息 {limit.cooldown_ms > 0 ? formatDuration(limit.cooldown_ms) : '默认'}
                    </span>
                    <span>
                      离开 {limit.session_gap_ms > 0 ? formatDuration(limit.session_gap_ms) : '默认'} 算结束
                    </span>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      <AppLimitDialog
        open={dialogOpen}
        editing={editing}
        knownPackages={knownPackages}
        submitting={submitting}
        onClose={() => {
          setDialogOpen(false);
          setEditing(null);
        }}
        onSubmit={(draft) => void submit(draft)}
      />
    </div>
  );
};

export default WellbeingPanel;
