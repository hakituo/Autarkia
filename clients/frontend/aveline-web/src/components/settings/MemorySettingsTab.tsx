import React, { useEffect, useMemo, useState } from 'react';
import { Database, Loader2, RefreshCw, Star, Trash2 } from 'lucide-react';
import { featureApi } from '../../api/featureApi';
import type { WeightedMemoryItem } from '../../types/features';

interface MemorySettingsTabProps {
  onRequestConfirm?: (options: {
    title: string;
    message: string;
    onConfirm: () => void;
    onCancel?: () => void;
    type?: 'danger' | 'info' | 'warning';
    showCancel?: boolean;
    confirmText?: string;
    cancelText?: string;
  }) => void;
}

/** 设置 - 记忆：加权记忆概览、单条删除、短期/全部清空。 */
export const MemorySettingsTab: React.FC<MemorySettingsTabProps> = ({ onRequestConfirm }) => {
  const [memories, setMemories] = useState<WeightedMemoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');

  const load = async () => {
    setLoading(true);
    setMessage('');
    try {
      const list = await featureApi.listMemories({ limit: 100, minWeight: 0.1 });
      setMemories(list);
    } catch (error: any) {
      setMessage(error?.message || '记忆加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const stats = useMemo(() => {
    const total = memories.length;
    const important = memories.filter((item) => item.is_important).length;
    const avgWeight = total
      ? memories.reduce((sum, item) => sum + Number(item.weight || 0), 0) / total
      : 0;
    return { total, important, avgWeight };
  }, [memories]);

  const confirmAction = (title: string, body: string, run: () => Promise<void> | void) => {
    if (!onRequestConfirm) {
      void run();
      return;
    }
    onRequestConfirm({
      title,
      message: body,
      type: 'danger',
      confirmText: '确认',
      cancelText: '取消',
      onConfirm: () => void run(),
    });
  };

  const deleteOne = (memory: WeightedMemoryItem) => {
    confirmAction('删除记忆', '这条加权记忆会被永久删除，确定继续？', async () => {
      try {
        await featureApi.deleteMemory(memory.id);
        setMemories((prev) => prev.filter((item) => item.id !== memory.id));
        setMessage('已删除 1 条记忆');
      } catch (error: any) {
        setMessage(error?.message || '删除失败');
      }
    });
  };

  const clearMemories = (mode: 'short' | 'all') => {
    const text =
      mode === 'all'
        ? '将清空全部长期记忆与权重记忆，且不可恢复。确定继续？'
        : '将清空当前会话的短期记忆，长期记忆保留。确定继续？';
    confirmAction('清空记忆', text, async () => {
      try {
        await featureApi.clearMemories(mode);
        setMessage(mode === 'all' ? '已清空全部记忆' : '已清空短期记忆');
        if (mode === 'all') setMemories([]);
        else await load();
      } catch (error: any) {
        setMessage(error?.message || '清空失败');
      }
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium text-white/90 flex items-center gap-2">
          <Database size={20} /> 记忆
        </h3>
        <button
          onClick={() => void load()}
          className="p-1.5 rounded-lg text-white/40 hover:text-white hover:bg-white/10 transition-colors"
          title="刷新"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="grid grid-cols-3 gap-2">
        {[
          { label: '记忆条数', value: stats.total },
          { label: '重要记忆', value: stats.important },
          { label: '平均权重', value: stats.avgWeight.toFixed(2) },
        ].map((item) => (
          <div key={item.label} className="rounded-xl border border-white/5 bg-black/20 px-3 py-3">
            <div className="text-[10px] uppercase tracking-wider text-white/30">{item.label}</div>
            <div className="text-lg text-white/85 font-mono mt-1">{item.value}</div>
          </div>
        ))}
      </div>

      {message && (
        <div className="text-[11px] text-white/55 bg-white/5 border border-white/10 rounded-lg px-3 py-2">
          {message}
        </div>
      )}

      <div className="space-y-2">
        <div className="text-[11px] uppercase tracking-wider text-white/35">最近记忆</div>
        <div className="max-h-72 overflow-y-auto custom-scrollbar space-y-1 pr-1">
          {loading && memories.length === 0 && (
            <div className="flex items-center gap-2 text-[11px] text-white/35 px-1 py-3">
              <Loader2 size={12} className="animate-spin" /> 加载中…
            </div>
          )}
          {!loading && memories.length === 0 && (
            <div className="text-[11px] text-white/30 px-1 py-3">还没有加权记忆</div>
          )}
          {memories.map((memory) => (
            <div
              key={memory.id}
              className="group flex items-start gap-2 px-3 py-2 rounded-lg border border-white/5 bg-black/20 hover:bg-white/5 transition-colors"
            >
              {memory.is_important ? (
                <Star size={11} className="text-purple-300 mt-1 shrink-0" />
              ) : (
                <span className="w-[11px] mt-1 shrink-0 flex justify-center">
                  <span className="w-1 h-1 rounded-full bg-white/25" />
                </span>
              )}
              <span className="flex-1 min-w-0 text-[11px] text-white/60 leading-relaxed">
                {memory.content}
                <span className="block text-[10px] text-white/25 font-mono mt-0.5">
                  weight {Number(memory.weight || 0).toFixed(2)}
                  {memory.source ? ` · ${memory.source}` : ''}
                </span>
              </span>
              <button
                onClick={() => deleteOne(memory)}
                className="opacity-0 group-hover:opacity-100 p-1 rounded text-white/30 hover:text-red-300 hover:bg-red-500/15 transition-all shrink-0"
                title="删除"
              >
                <Trash2 size={11} />
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => clearMemories('short')}
          className="px-3 py-2 rounded-lg text-xs bg-blue-500/10 text-blue-200 border border-blue-500/25 hover:bg-blue-500/20 transition-colors"
        >
          清空短期记忆
        </button>
        <button
          onClick={() => clearMemories('all')}
          className="px-3 py-2 rounded-lg text-xs bg-red-500/10 text-red-200 border border-red-500/25 hover:bg-red-500/20 transition-colors"
        >
          清空全部记忆
        </button>
      </div>
    </div>
  );
};

export default MemorySettingsTab;
