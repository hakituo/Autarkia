import React, { useMemo } from 'react';
import { CalendarClock, CircleDot } from 'lucide-react';
import type { LifeStatusPayload } from '../../types/features';

interface ScheduleTimelineProps {
  status: LifeStatusPayload | null;
}

const ACTIVITY_LABELS: Record<string, string> = {
  sleeping: '睡觉',
  napping: '午睡',
  working: '工作',
  studying: '学习',
  eating: '吃饭',
  cooking: '做饭',
  commuting: '通勤',
  resting: '休息',
  idle: '空闲',
  chatting: '聊天',
  exercising: '运动',
};

interface SlotView {
  key: string;
  label: string;
  start: string;
  end: string;
  chatEligible: boolean;
  status: string;
}

const formatClock = (iso: string): string => {
  const text = String(iso || '');
  const match = text.match(/T(\d{2}):(\d{2})/);
  if (match) return `${match[1]}:${match[2]}`;
  return text.slice(11, 16) || '--:--';
};

/** 角色日程：读 /life/status 的 daily_plan.slots，高亮当前时段。 */
export const ScheduleTimeline: React.FC<ScheduleTimelineProps> = ({ status }) => {
  const slots = useMemo<SlotView[]>(() => {
    const plan: any = status?.daily_plan;
    const raw = Array.isArray(plan?.slots)
      ? plan.slots
      : Array.isArray(plan?.activities)
        ? plan.activities
        : [];
    return raw
      .map((slot: any, index: number): SlotView => ({
        key: `${slot?.activity || 'idle'}-${slot?.planned_start || index}`,
        label: ACTIVITY_LABELS[String(slot?.activity)] || String(slot?.activity || '未知'),
        start: formatClock(slot?.planned_start || slot?.start || ''),
        end: formatClock(slot?.planned_end || slot?.end || ''),
        chatEligible: slot?.chat_eligible !== false,
        status: String(slot?.execution_status || 'pending'),
      }))
      .sort((a: SlotView, b: SlotView) => a.start.localeCompare(b.start));
  }, [status]);

  const currentActivity = String(status?.daily_plan?.current_activity || status?.activity || '');
  const nowClock = new Date().toTimeString().slice(0, 5);

  if (slots.length === 0) {
    return (
      <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-6 text-center">
        <CalendarClock size={18} className="mx-auto text-white/25 mb-2" />
        <div className="text-xs text-white/35">今天还没有生成日程</div>
        <div className="text-[10px] text-white/20 mt-1">
          角色会在每日计划生成后展示时间段与可聊状态
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      {slots.map((slot) => {
        const isNow =
          slot.start <= nowClock && (slot.end >= nowClock || slot.end < slot.start);
        const isCurrent = isNow || (currentActivity && slot.label === ACTIVITY_LABELS[currentActivity]);
        return (
          <div
            key={slot.key}
            className={`flex items-center gap-3 px-3 py-2 rounded-lg border transition-colors ${
              isCurrent
                ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-100'
                : 'bg-black/20 border-white/5 text-white/60'
            }`}
          >
            <span className="font-mono text-[11px] w-24 shrink-0 text-white/45">
              {slot.start} - {slot.end}
            </span>
            <span className="text-xs flex-1 truncate">{slot.label}</span>
            {!slot.chatEligible && (
              <span className="text-[10px] text-amber-300/80 border border-amber-500/20 rounded px-1.5 py-0.5">
                免打扰
              </span>
            )}
            {isCurrent && <CircleDot size={12} className="text-emerald-400 animate-pulse" />}
          </div>
        );
      })}
    </div>
  );
};

export default ScheduleTimeline;
