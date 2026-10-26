import React, { useMemo, useState } from 'react';
import { Check, Droplets, Plus } from 'lucide-react';
import { dailyApi } from '../../api/extendedApi';
import type { HealthSnapshot } from '../../api/extendedApi';
import { LifeBar, LifeEmpty, LifeSection, StatTile } from './LifeUi';
import { formatClock, type LifeNutrition, type LifePortrait } from './types';

const DEFAULT_GOAL_ML = 2000;

const QUICK_AMOUNTS = [200, 250, 500];

export const LifeWaterTab: React.FC<{
  nutrition: LifeNutrition;
  health: HealthSnapshot | null;
  portrait: LifePortrait | null;
  onRecorded: () => void;
}> = ({ nutrition, health, portrait, onRecorded }) => {
  const [custom, setCustom] = useState('');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const entries = useMemo(
    () =>
      (nutrition.water_intake_entries || [])
        .map((entry) => ({
          amount: Number(entry.amount_ml || 0),
          time: entry.time || '',
        }))
        .filter((entry) => entry.amount > 0)
        .sort((a, b) => String(b.time).localeCompare(String(a.time))),
    [nutrition.water_intake_entries],
  );

  const deviceTotal = entries.reduce((sum, entry) => sum + entry.amount, 0);
  const portraitTotal = Number(portrait?.drink?.total_ml || 0);
  const total = deviceTotal > 0 ? deviceTotal : portraitTotal;
  const goal = Number(health?.water_intake_goal_ml || DEFAULT_GOAL_ML);

  const record = async (rawAmount: number) => {
    // 后端 amount_ml 限制 1..5000
    const amountMl = Math.min(5000, Math.max(1, Math.round(rawAmount)));
    if (!Number.isFinite(amountMl) || amountMl <= 0) return;
    setSaving(true);
    setMessage(null);
    try {
      const res = await dailyApi.recordDrink({ amount_ml: Math.round(amountMl) });
      if ((res?.status ?? 'success') === 'success') {
        setMessage(res?.message || `已记录 ${Math.round(amountMl)} ml`);
        setCustom('');
        onRecorded();
      } else {
        setMessage(res?.message || '记录失败');
      }
    } catch (e: any) {
      setMessage(e?.message || '记录失败，请检查后端连接');
    } finally {
      setSaving(false);
      window.setTimeout(() => setMessage(null), 3000);
    }
  };

  return (
    <div className="space-y-3">
      <LifeSection
        title="今日饮水"
        icon={<Droplets size={16} />}
        subtitle={`目标 ${Math.round(goal)} ml`}
        action={<span className="text-[11px] text-white/35">{Math.round(total)} / {Math.round(goal)} ml</span>}
      >
        <div className="space-y-3">
          <LifeBar ratio={total / goal} tone="sky" height="h-2.5" />
          <div className="grid grid-cols-3 gap-2">
            <StatTile label="已饮" value={Math.round(total)} unit="ml" tone="sky" />
            <StatTile label="剩余" value={Math.max(0, Math.round(goal - total))} unit="ml" />
            <StatTile label="次数" value={entries.length || portrait?.drink?.count || 0} unit="次" />
          </div>

          <div className="flex flex-wrap items-center gap-2 pt-1">
            {QUICK_AMOUNTS.map((amount) => (
              <button
                key={amount}
                disabled={saving}
                onClick={() => void record(amount)}
                className="flex items-center gap-1 px-3 py-1.5 rounded-full bg-sky-500/10 border border-sky-500/20 text-sky-200 text-xs hover:bg-sky-500/20 transition-colors disabled:opacity-40"
              >
                <Plus size={12} />
                {amount} ml
              </button>
            ))}
            <div className="flex items-center gap-1.5">
              <input
                value={custom}
                onChange={(e) => setCustom(e.target.value.replace(/[^\d]/g, ''))}
                placeholder="自定义"
                inputMode="numeric"
                className="w-20 bg-white/5 border border-white/10 rounded-full px-3 py-1.5 text-xs text-white/80 outline-none focus:border-sky-400/40"
              />
              <button
                disabled={saving || !custom}
                onClick={() => void record(Number(custom))}
                className="px-3 py-1.5 rounded-full bg-white/10 border border-white/10 text-xs text-white/70 hover:bg-white/15 transition-colors disabled:opacity-40"
              >
                记录
              </button>
            </div>
          </div>

          {message && (
            <div className="flex items-center gap-1.5 text-[11px] text-emerald-300">
              <Check size={12} />
              {message}
            </div>
          )}
        </div>
      </LifeSection>

      <LifeSection title="饮水记录" subtitle="按时间倒序">
        {entries.length === 0 ? (
          <LifeEmpty
            icon={<Droplets size={32} />}
            title="今天还没有饮水记录"
            hint="可以手动打卡，或在安卓端同步 Samsung Health 的饮水数据。"
          />
        ) : (
          <ul className="divide-y divide-white/5">
            {entries.map((entry, index) => (
              <li key={`${entry.time}-${index}`} className="flex items-center justify-between py-2">
                <span className="text-xs text-white/45 tabular-nums">{formatClock(entry.time)}</span>
                <span className="text-sm text-sky-200 tabular-nums">{Math.round(entry.amount)} ml</span>
              </li>
            ))}
          </ul>
        )}
      </LifeSection>
    </div>
  );
};
