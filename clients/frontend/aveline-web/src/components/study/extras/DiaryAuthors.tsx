import React, { useEffect, useMemo, useState } from 'react';
import { CalendarDays, Loader2, RefreshCw, UserRound } from 'lucide-react';
import { featureApi } from '../../../api/featureApi';
import type { DiaryEntry } from '../../../types/features';

const todayStr = (): string => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(
    now.getDate(),
  ).padStart(2, '0')}`;
};

const authorOf = (entry: DiaryEntry): string =>
  String(entry.source_label || entry.source || '未知作者');

/** 日记按作者筛选：后端已透传 source / source_label，前端只做分组与过滤。 */
export const DiaryAuthors: React.FC = () => {
  const [date, setDate] = useState(todayStr());
  const [entries, setEntries] = useState<DiaryEntry[]>([]);
  const [author, setAuthor] = useState<string>('all');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = async (targetDate: string) => {
    setLoading(true);
    setError('');
    try {
      const list = await featureApi.listDiary(targetDate);
      setEntries(Array.isArray(list) ? list : []);
    } catch (err: any) {
      setError(err?.message || '日记加载失败');
      setEntries([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load(date);
  }, [date]);

  const authors = useMemo(() => {
    const counts = new Map<string, number>();
    entries.forEach((entry) => {
      const key = authorOf(entry);
      counts.set(key, (counts.get(key) || 0) + 1);
    });
    return Array.from(counts.entries()).map(([name, count]) => ({ name, count }));
  }, [entries]);

  const visible = useMemo(
    () => (author === 'all' ? entries : entries.filter((entry) => authorOf(entry) === author)),
    [entries, author],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 bg-black/30 border border-white/10 rounded-lg px-2.5 py-1.5">
          <CalendarDays size={13} className="text-white/35" />
          <input
            type="date"
            value={date}
            onChange={(event) => setDate(event.target.value || todayStr())}
            className="bg-transparent text-xs text-white outline-none [color-scheme:dark]"
          />
        </div>
        <button
          onClick={() => void load(date)}
          className="p-1.5 rounded-lg text-white/40 hover:text-white hover:bg-white/10"
          title="刷新"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
        </button>
        <span className="text-[11px] text-white/30">{entries.length} 条记录</span>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <button
          onClick={() => setAuthor('all')}
          className={`px-2.5 py-1 rounded-lg text-[11px] border transition-colors ${
            author === 'all'
              ? 'bg-emerald-500/15 text-emerald-200 border-emerald-500/30'
              : 'text-white/45 border-white/10 hover:text-white/80'
          }`}
        >
          全部 {entries.length}
        </button>
        {authors.map((item) => (
          <button
            key={item.name}
            onClick={() => setAuthor(item.name)}
            className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] border transition-colors ${
              author === item.name
                ? 'bg-emerald-500/15 text-emerald-200 border-emerald-500/30'
                : 'text-white/45 border-white/10 hover:text-white/80'
            }`}
          >
            <UserRound size={10} /> {item.name} {item.count}
          </button>
        ))}
      </div>

      {error && (
        <div className="text-[11px] text-red-300/80 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      <div className="space-y-2">
        {loading && visible.length === 0 && (
          <div className="flex items-center gap-2 text-[11px] text-white/35 px-1 py-4">
            <Loader2 size={12} className="animate-spin" /> 加载中…
          </div>
        )}
        {!loading && visible.length === 0 && !error && (
          <div className="text-[11px] text-white/30 px-1 py-4">这一天没有日记</div>
        )}
        {visible.map((entry) => (
          <div
            key={entry.id}
            className="rounded-xl border border-white/5 bg-black/20 px-4 py-3 hover:bg-white/5 transition-colors"
          >
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/5 text-white/55">
                {authorOf(entry)}
              </span>
              {entry.time_str && (
                <span className="text-[10px] font-mono text-white/25">{entry.time_str}</span>
              )}
              {entry.mood && (
                <span className="text-[10px] text-amber-200/70">心情 {entry.mood}</span>
              )}
              {(entry.tags || []).map((tag) => (
                <span key={tag} className="text-[10px] text-sky-200/60">
                  #{tag}
                </span>
              ))}
            </div>
            <div className="text-[12px] text-white/70 leading-relaxed whitespace-pre-wrap">
              {entry.content}
            </div>
            {entry.thought && (
              <div className="mt-1.5 text-[11px] text-white/35 italic leading-relaxed">
                {entry.thought}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

export default DiaryAuthors;
