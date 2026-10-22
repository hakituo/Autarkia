import React, { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, Loader2, PlayCircle, RefreshCw, Square, Target } from 'lucide-react';
import { featureApi } from '../../../api/featureApi';

const formatDuration = (seconds: number): string => {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return minutes > 0 ? `${minutes} 分 ${rest} 秒` : `${rest} 秒`;
};

const SUMMARY_LABELS: Record<string, string> = {
  date: '日期',
  new_words: '新词',
  reviewed_words: '复习词',
  total_words: '总词数',
  duration_minutes: '学习时长(分)',
  sessions: '会话数',
  accuracy: '正确率',
  streak_days: '连续天数',
};

/** 词汇复习会话总结：当前会话统计 + 今日摘要 + 开始/结束会话。 */
export const VocabSessionSummary: React.FC = () => {
  const [stats, setStats] = useState<Record<string, any>>({});
  const [summary, setSummary] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const [statsRes, summaryRes] = await Promise.all([
        featureApi.getVocabSessionStats().catch(() => ({})),
        featureApi.getVocabSummary().catch(() => ({})),
      ]);
      setStats(statsRes || {});
      setSummary(summaryRes || {});
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => window.clearInterval(timer);
  }, []);

  const active = Boolean(stats.active);
  const accuracy = Number(stats.accuracy || 0);

  const summaryRows = useMemo(
    () =>
      Object.entries(summary || {})
        .filter(([, value]) => typeof value === 'number' || typeof value === 'string')
        .slice(0, 12)
        .map(([key, value]) => ({
          key,
          label: SUMMARY_LABELS[key] || key,
          value: String(value),
        })),
    [summary],
  );

  const start = async () => {
    setBusy('start');
    setMessage('');
    try {
      await featureApi.startVocabSession();
      setMessage('已开始新的复习会话');
      await load();
    } catch (error: any) {
      setMessage(error?.message || '开始会话失败');
    } finally {
      setBusy('');
    }
  };

  const end = async () => {
    setBusy('end');
    setMessage('');
    try {
      await featureApi.endVocabSession();
      setMessage('会话已结束并结算');
      await load();
    } catch (error: any) {
      setMessage(error?.message || '结束会话失败');
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-wider text-white/35 flex items-center gap-1.5">
          <Target size={11} /> 复习会话
        </span>
        <button
          onClick={() => void load()}
          className="p-1.5 rounded-lg text-white/40 hover:text-white hover:bg-white/10"
          title="刷新"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="rounded-xl border border-white/10 bg-black/25 p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                active ? 'bg-emerald-400 animate-pulse' : 'bg-white/20'
              }`}
            />
            <span className="text-xs text-white/75">
              {active ? '会话进行中' : '当前没有进行中的会话'}
            </span>
          </div>
          <span className="text-[11px] font-mono text-white/35">
            {formatDuration(Number(stats.duration || 0))}
          </span>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {[
            { label: '复习词数', value: Number(stats.words_reviewed || 0) },
            { label: '掌握词数', value: Number(stats.words_mastered || 0) },
            { label: '正确率', value: `${accuracy.toFixed(1)}%` },
            { label: '连续正确', value: Number(stats.streak || 0) },
          ].map((item) => (
            <div key={item.label} className="rounded-lg bg-white/5 px-3 py-2">
              <div className="text-[10px] text-white/35">{item.label}</div>
              <div className="text-base text-white/85 font-mono mt-0.5">{item.value}</div>
            </div>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => void start()}
            disabled={Boolean(busy) || active}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500/15 text-emerald-200 border border-emerald-500/25 hover:bg-emerald-500/25 text-[11px] disabled:opacity-40 transition-colors"
          >
            {busy === 'start' ? <Loader2 size={12} className="animate-spin" /> : <PlayCircle size={12} />}
            开始会话
          </button>
          <button
            onClick={() => void end()}
            disabled={Boolean(busy) || !active}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 text-white/70 border border-white/10 hover:bg-white/10 text-[11px] disabled:opacity-40 transition-colors"
          >
            {busy === 'end' ? <Loader2 size={12} className="animate-spin" /> : <Square size={12} />}
            结束并结算
          </button>
          {message && (
            <span className="text-[11px] text-emerald-300/80 flex items-center gap-1">
              <CheckCircle2 size={11} /> {message}
            </span>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-white/10 bg-black/20 p-4">
        <div className="text-[11px] uppercase tracking-wider text-white/35 mb-2">今日学习摘要</div>
        {summaryRows.length === 0 ? (
          <div className="text-[11px] text-white/30">暂无摘要数据</div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {summaryRows.map((row) => (
              <div key={row.key} className="rounded-lg bg-white/5 px-3 py-2">
                <div className="text-[10px] text-white/35 truncate">{row.label}</div>
                <div className="text-sm text-white/80 font-mono mt-0.5 truncate">{row.value}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default VocabSessionSummary;
