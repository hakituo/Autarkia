import React, { useEffect, useMemo, useState } from 'react';
import { GitBranch, Loader2, RefreshCw, Star, Trash2 } from 'lucide-react';
import { featureApi } from '../../api/featureApi';
import type { WeightedMemoryItem } from '../../types/features';

interface WorldlineTreeProps {
  scope: string;
  personaFile?: string;
  onRequestDelete?: (memory: WeightedMemoryItem, confirm: () => void) => void;
}

interface DayGroup {
  day: string;
  items: WeightedMemoryItem[];
}

const formatDay = (timestamp: number): string => {
  const ts = timestamp > 1e12 ? timestamp : timestamp * 1000;
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return '未知日期';
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(
    date.getDate(),
  ).padStart(2, '0')}`;
};

const formatClock = (timestamp: number): string => {
  const ts = timestamp > 1e12 ? timestamp : timestamp * 1000;
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return '--:--';
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
};

/** 记忆世界线树：按日期分叉、按权重决定节点粗细，重要记忆标成分支点。 */
export const WorldlineTree: React.FC<WorldlineTreeProps> = ({
  scope,
  personaFile,
  onRequestDelete,
}) => {
  const [memories, setMemories] = useState<WeightedMemoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const list = await featureApi.listMemories({ limit: 200, minWeight: 0.1, persona: personaFile });
      setMemories(list);
    } catch (err: any) {
      setError(err?.message || '记忆加载失败');
      setMemories([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // 只在角色切换时重拉，避免轮询把展开状态刷掉
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, personaFile]);

  const groups = useMemo<DayGroup[]>(() => {
    const buckets = new Map<string, WeightedMemoryItem[]>();
    memories.forEach((memory) => {
      const day = formatDay(memory.timestamp);
      if (!buckets.has(day)) buckets.set(day, []);
      buckets.get(day)!.push(memory);
    });
    return Array.from(buckets.entries())
      .map(([day, items]) => ({
        day,
        items: items.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0)),
      }))
      .sort((a, b) => b.day.localeCompare(a.day));
  }, [memories]);

  const handleDelete = (memory: WeightedMemoryItem) => {
    const run = async () => {
      try {
        await featureApi.deleteMemory(memory.id);
        setMemories((prev) => prev.filter((item) => item.id !== memory.id));
      } catch {
        setError('删除失败，请稍后重试');
      }
    };
    if (onRequestDelete) onRequestDelete(memory, () => void run());
    else void run();
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-white/70">
          <GitBranch size={14} className="text-purple-300" />
          <span className="text-xs">记忆世界线</span>
          <span className="text-[10px] text-white/30 font-mono">{memories.length} 节点</span>
        </div>
        <button
          onClick={() => void load()}
          className="p-1.5 rounded-lg text-white/40 hover:text-white hover:bg-white/10 transition-colors"
          title="刷新记忆"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {error && (
        <div className="text-[11px] text-red-300/80 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {loading && memories.length === 0 && (
        <div className="flex items-center gap-2 text-[11px] text-white/35 px-2 py-4">
          <Loader2 size={12} className="animate-spin" /> 正在读取世界线…
        </div>
      )}

      {!loading && memories.length === 0 && !error && (
        <div className="text-[11px] text-white/30 px-2 py-4">还没有形成记忆节点</div>
      )}

      <div className="space-y-4">
        {groups.map((group) => (
          <div key={group.day} className="relative pl-4">
            <div className="absolute left-[3px] top-2 bottom-0 w-px bg-gradient-to-b from-white/15 to-transparent" />
            <div className="flex items-center gap-2 mb-1.5">
              <span className="absolute left-0 w-[7px] h-[7px] rounded-full bg-purple-400/80 shadow-[0_0_8px_rgba(192,132,252,0.7)]" />
              <span className="text-[11px] font-mono text-white/45">{group.day}</span>
              <span className="text-[10px] text-white/20">{group.items.length}</span>
            </div>

            <div className="space-y-1">
              {group.items.map((memory) => {
                const isBranch = Boolean(memory.is_important) || Number(memory.weight) >= 2;
                const open = expanded === memory.id;
                return (
                  <div
                    key={memory.id}
                    className={`group rounded-lg border px-3 py-2 transition-colors cursor-pointer ${
                      isBranch
                        ? 'border-purple-500/25 bg-purple-500/5 hover:bg-purple-500/10'
                        : 'border-white/5 bg-black/20 hover:bg-white/5'
                    }`}
                    onClick={() => setExpanded(open ? null : memory.id)}
                  >
                    <div className="flex items-center gap-2">
                      {isBranch ? (
                        <Star size={11} className="text-purple-300 shrink-0" />
                      ) : (
                        <span className="w-[11px] h-[11px] shrink-0 flex items-center justify-center">
                          <span className="w-1 h-1 rounded-full bg-white/30" />
                        </span>
                      )}
                      <span className="text-[10px] font-mono text-white/30 shrink-0">
                        {formatClock(memory.timestamp)}
                      </span>
                      <span
                        className={`text-[11px] flex-1 min-w-0 ${
                          open ? 'text-white/80 whitespace-pre-wrap' : 'text-white/55 truncate'
                        }`}
                      >
                        {memory.content}
                      </span>
                      <span className="text-[10px] font-mono text-white/25 shrink-0">
                        {Number(memory.weight || 0).toFixed(1)}
                      </span>
                      <button
                        onClick={(event) => {
                          event.stopPropagation();
                          handleDelete(memory);
                        }}
                        className="opacity-0 group-hover:opacity-100 p-1 rounded text-white/30 hover:text-red-300 hover:bg-red-500/15 transition-all shrink-0"
                        title="删除这条记忆"
                      >
                        <Trash2 size={10} />
                      </button>
                    </div>

                    {open && (memory.topics?.length || memory.emotions?.length) ? (
                      <div className="flex flex-wrap gap-1 mt-2 pl-5">
                        {(memory.topics || []).map((topic) => (
                          <span
                            key={`t-${topic}`}
                            className="text-[10px] px-1.5 py-0.5 rounded bg-white/5 text-white/45"
                          >
                            #{topic}
                          </span>
                        ))}
                        {(memory.emotions || []).map((emotion) => (
                          <span
                            key={`e-${emotion}`}
                            className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-200/70"
                          >
                            {emotion}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default WorldlineTree;
