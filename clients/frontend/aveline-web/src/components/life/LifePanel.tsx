import React, { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Activity, CalendarClock, Droplets, HeartPulse, RefreshCw, Utensils } from 'lucide-react';
import { useLifeData } from './useLifeData';
import { LifeHealthTab } from './LifeHealthTab';
import { LifeScheduleTab } from './LifeScheduleTab';
import { LifeWaterTab } from './LifeWaterTab';
import { LifeMealTab } from './LifeMealTab';
import { LifeLoading } from './LifeUi';
import type { LifeTab } from './types';

const TABS: Array<{ id: LifeTab; label: string; icon: React.ReactNode }> = [
  { id: 'health', label: '健康', icon: <HeartPulse size={14} /> },
  { id: 'schedule', label: '日程', icon: <CalendarClock size={14} /> },
  { id: 'water', label: '饮水', icon: <Droplets size={14} /> },
  { id: 'meal', label: '餐食', icon: <Utensils size={14} /> },
];

/**
 * 生活模块：对齐安卓 LifeScreen 的四个 Tab。
 * 网页端只做「展示 + 手动补录」，设备原始数据仍由安卓端同步到后端。
 */
export const LifePanel: React.FC<{ platform?: 'web' | 'mobile' }> = ({ platform = 'web' }) => {
  const [tab, setTab] = useState<LifeTab>('health');
  const { data, loading, error, refresh } = useLifeData();

  return (
    <div className={`flex flex-col h-full ${platform === 'mobile' ? '' : 'p-4 md:p-6'} overflow-hidden`}>
      <div className="shrink-0 flex items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center shrink-0">
            <Activity className="text-emerald-300" size={18} />
          </div>
          <div className="min-w-0">
            <h2 className="text-lg md:text-xl font-semibold text-white/95 tracking-wide">Life</h2>
            <p className="text-[10px] md:text-xs text-white/40 truncate">
              健康 / 作息 / 饮水 / 餐食
            </p>
          </div>
        </div>
        <button
          onClick={() => void refresh()}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white/5 border border-white/10 text-[11px] text-white/55 hover:bg-white/10 transition-colors disabled:opacity-40"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      </div>

      <div className="shrink-0 flex items-center gap-1 mb-3 overflow-x-auto no-scrollbar">
        {TABS.map((item) => (
          <button
            key={item.id}
            onClick={() => setTab(item.id)}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs whitespace-nowrap border transition-all ${
              tab === item.id
                ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25'
                : 'bg-white/5 text-white/40 border-transparent hover:text-white/70 hover:bg-white/10'
            }`}
          >
            {item.icon}
            {item.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="shrink-0 mb-3 rounded-xl border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-200">
          {error}
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar pr-0.5">
        {loading && !data.health && !data.portrait ? (
          <LifeLoading text="正在加载生活数据…" />
        ) : (
          <AnimatePresence mode="wait">
            <motion.div
              key={tab}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.18 }}
            >
              {tab === 'health' && <LifeHealthTab health={data.health} />}
              {tab === 'schedule' && (
                <LifeScheduleTab portrait={data.portrait} onSaved={() => void refresh()} />
              )}
              {tab === 'water' && (
                <LifeWaterTab
                  nutrition={data.nutrition}
                  health={data.health}
                  portrait={data.portrait}
                  onRecorded={() => void refresh()}
                />
              )}
              {tab === 'meal' && (
                <LifeMealTab
                  nutrition={data.nutrition}
                  health={data.health}
                  portrait={data.portrait}
                />
              )}
            </motion.div>
          </AnimatePresence>
        )}
      </div>
    </div>
  );
};

export default LifePanel;
