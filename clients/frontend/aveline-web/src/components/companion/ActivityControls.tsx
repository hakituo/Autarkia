import React, { useState } from 'react';
import { AlarmClock, BellRing, Coffee, FastForward, Loader2, Moon, Sun } from 'lucide-react';
import { featureApi, unwrap } from '../../api/featureApi';
import type { LifeStatusPayload } from '../../types/features';

interface ActivityControlsProps {
  scope: string;
  conversationId: string | null;
  status: LifeStatusPayload | null;
  onRefresh: () => void;
}

const ACTIVITY_LABELS: Record<string, string> = {
  sleeping: '睡觉',
  napping: '午睡',
  working: '工作',
  studying: '学习',
  eating: '吃饭',
  commuting: '通勤',
  resting: '休息',
  idle: '空闲',
  chatting: '聊天',
};

/** 唤醒 / 打断 / 跳过 / 延长：直接驱动后端 character_daily 的当前活动。 */
export const ActivityControls: React.FC<ActivityControlsProps> = ({
  scope,
  conversationId,
  status,
  onRefresh,
}) => {
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState('');

  const activity = String(status?.activity || 'idle');
  const isSleeping = Boolean((status?.sleep_summary as any)?.is_sleeping);
  const chatEligible = status?.activity_chat_eligible !== false;

  const run = async (action: string, task: () => Promise<any>) => {
    if (busy) return;
    setBusy(action);
    setMessage('');
    try {
      const res = await task();
      const data = unwrap<Record<string, any>>(res, {});
      const text =
        data?.message ||
        data?.detail ||
        (res as any)?.message ||
        (action === 'wake' ? '已尝试唤醒' : '操作已提交');
      setMessage(String(text));
      onRefresh();
    } catch (error: any) {
      setMessage(error?.message || '操作失败，请稍后重试');
    } finally {
      setBusy(null);
    }
  };

  const buttons = [
    {
      key: 'wake',
      label: isSleeping ? '立即唤醒' : '确认在忙',
      icon: isSleeping ? Sun : BellRing,
      hint: '让她从睡眠/免打扰里回到可聊天状态',
      run: () => featureApi.wakeRole({ role_id: scope, conversation_id: conversationId || undefined }),
      tone: 'emerald',
    },
    {
      key: 'interrupt',
      label: '打断当前活动',
      icon: FastForward,
      hint: '打开一个中断窗口，当前活动暂时让位给聊天',
      run: () =>
        featureApi.interruptActivity({
          role_id: scope,
          conversation_id: conversationId || undefined,
          message: '用户主动打断',
        }),
      tone: 'amber',
    },
    {
      key: 'skip',
      label: '跳过这个活动',
      icon: Coffee,
      hint: '标记当前活动为已跳过，不再提醒她回去',
      run: () =>
        featureApi.skipActivity({
          role_id: scope,
          conversation_id: conversationId || undefined,
          message: '用户要求跳过',
        }),
      tone: 'zinc',
    },
    {
      key: 'extend',
      label: '延长 15 分钟',
      icon: AlarmClock,
      hint: '把当前中断窗口再延长 900 秒',
      run: () =>
        featureApi.extendActivity({
          role_id: scope,
          conversation_id: conversationId || undefined,
          extend_seconds: 900,
          message: '用户要求延长',
        }),
      tone: 'sky',
    },
  ] as const;

  const toneClass = (tone: string) => {
    switch (tone) {
      case 'emerald':
        return 'bg-emerald-500/10 text-emerald-200 border-emerald-500/25 hover:bg-emerald-500/20';
      case 'amber':
        return 'bg-amber-500/10 text-amber-200 border-amber-500/25 hover:bg-amber-500/20';
      case 'sky':
        return 'bg-sky-500/10 text-sky-200 border-sky-500/25 hover:bg-sky-500/20';
      default:
        return 'bg-white/5 text-white/70 border-white/10 hover:bg-white/10';
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between rounded-xl border border-white/10 bg-black/25 px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center">
            {isSleeping ? (
              <Moon size={15} className="text-indigo-300" />
            ) : (
              <Sun size={15} className="text-amber-300" />
            )}
          </div>
          <div>
            <div className="text-sm text-white/85">
              当前活动：{ACTIVITY_LABELS[activity] || activity}
            </div>
            <div className="text-[11px] text-white/35">
              {isSleeping ? '正在睡觉' : chatEligible ? '可随时聊天' : '忙碌中，消息会先积攒'}
            </div>
          </div>
        </div>
        <span
          className={`text-[10px] px-2 py-1 rounded-full border ${
            chatEligible
              ? 'text-emerald-300 border-emerald-500/25 bg-emerald-500/10'
              : 'text-amber-300 border-amber-500/25 bg-amber-500/10'
          }`}
        >
          {chatEligible ? 'CHAT READY' : 'DO NOT DISTURB'}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {buttons.map((button) => {
          const Icon = button.icon;
          return (
            <button
              key={button.key}
              onClick={() => void run(button.key, button.run)}
              disabled={Boolean(busy)}
              title={button.hint}
              className={`flex items-start gap-2 px-3 py-2.5 rounded-xl border text-left transition-colors disabled:opacity-50 ${toneClass(
                button.tone,
              )}`}
            >
              <span className="mt-0.5">
                {busy === button.key ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <Icon size={13} />
                )}
              </span>
              <span className="min-w-0">
                <span className="block text-xs">{button.label}</span>
                <span className="block text-[10px] opacity-60 mt-0.5 leading-snug">
                  {button.hint}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      {message && (
        <div className="text-[11px] text-white/50 bg-white/5 border border-white/10 rounded-lg px-3 py-2">
          {message}
        </div>
      )}
    </div>
  );
};

export default ActivityControls;
