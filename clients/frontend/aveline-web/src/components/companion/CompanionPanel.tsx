import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  CalendarClock,
  GitBranch,
  Heart,
  RefreshCw,
  Settings2,
} from 'lucide-react';
import { featureApi } from '../../api/featureApi';
import { useFeatureStore } from '../../store/useFeatureStore';
import { resolveRoleScopeFromConversationId } from '../../utils/conversation';
import type { LifeStatusPayload } from '../../types/features';
import type { Model } from '../../types';
import ActivityControls from './ActivityControls';
import ScheduleTimeline from './ScheduleTimeline';
import RoleRuntimeSettings from './RoleRuntimeSettings';
import WorldlineTree from './WorldlineTree';

interface CompanionPanelProps {
  currentSessionId: string | null;
  models: Model[];
  selectedModel: Model | null;
  onSelectModel: (model: Model) => void;
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

type TabKey = 'activity' | 'schedule' | 'settings' | 'worldline';

const TABS: Array<{ key: TabKey; label: string; icon: React.ElementType }> = [
  { key: 'activity', label: '状态与唤醒', icon: Activity },
  { key: 'schedule', label: '角色日程', icon: CalendarClock },
  { key: 'settings', label: '人设与模型', icon: Settings2 },
  { key: 'worldline', label: '世界线', icon: GitBranch },
];

const METRIC_LABELS: Record<string, string> = {
  energy: '精力',
  hunger: '饱腹',
  thirst: '水分',
  mood_score: '心情',
  stress: '压力',
  social_desire: '社交',
};

const METRIC_MAX: Record<string, number> = {
  energy: 100,
  hunger: 100,
  thirst: 100,
  mood_score: 100,
  stress: 100,
  social_desire: 100,
};

/** 伴侣详情面板：状态/活动、日程、角色级设置、记忆世界线。 */
const CompanionPanel: React.FC<CompanionPanelProps> = ({
  currentSessionId,
  models,
  selectedModel,
  onSelectModel,
  onRequestConfirm,
}) => {
  const [tab, setTab] = useState<TabKey>('activity');
  const [status, setStatus] = useState<LifeStatusPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const roles = useFeatureStore((s) => s.roles);
  const loadRoles = useFeatureStore((s) => s.loadRoles);
  const [currentPersonaFile, setCurrentPersonaFile] = useState('');

  const rawScope = useMemo(
    () => resolveRoleScopeFromConversationId(currentSessionId || 'default_user'),
    [currentSessionId],
  );

  // default_user 这类主用户会话反解不出角色，用后端「当前人设」兜底，
  // 否则伴侣详情会显示成 scope=user 的空面板。
  const scope = useMemo(() => {
    if (rawScope !== 'user' && rawScope !== 'unknown') return rawScope;
    const matched = roles.find((item) => item.persona_file === currentPersonaFile);
    return matched?.scope || 'aveline';
  }, [rawScope, roles, currentPersonaFile]);

  const role = roles.find((item) => item.scope === scope) || null;

  useEffect(() => {
    featureApi
      .getCurrentPersona()
      .then((data: any) => setCurrentPersonaFile(String(data?.filename || '')))
      .catch(() => setCurrentPersonaFile(''));
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await featureApi.getLifeStatus(scope);
      setStatus(data);
    } catch (err: any) {
      setError(err?.message || '生命状态读取失败');
    } finally {
      setLoading(false);
    }
  }, [scope]);

  useEffect(() => {
    if (roles.length === 0) void loadRoles();
  }, [roles.length, loadRoles]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 45000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const metrics = useMemo(() => {
    const source: Record<string, any> = (status?.life_status as any) || {};
    return Object.keys(METRIC_LABELS)
      .filter((key) => typeof source[key] === 'number')
      .map((key) => ({
        key,
        label: METRIC_LABELS[key],
        value: Number(source[key]),
        max: METRIC_MAX[key] || 100,
      }));
  }, [status]);

  const handleDeleteMemory = (_memory: unknown, confirm: () => void) => {
    if (!onRequestConfirm) {
      confirm();
      return;
    }
    onRequestConfirm({
      title: '删除记忆节点',
      message: '这条记忆会从世界线中移除，且不可恢复。确定删除？',
      type: 'danger',
      confirmText: '删除',
      cancelText: '取消',
      onConfirm: confirm,
    });
  };

  return (
    <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar p-6">
      <div className="max-w-4xl mx-auto space-y-5">
        {/* 角色头部 */}
        <div className="rounded-2xl border border-white/10 bg-black/25 p-5 flex items-center gap-4">
          <div className="w-14 h-14 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center text-3xl shrink-0">
            {role?.avatar || '🪐'}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-base text-white/90 truncate">
                {role?.display_name || role?.name || scope}
              </span>
              <span className="text-[10px] font-mono text-white/30 border border-white/10 rounded px-1.5 py-0.5">
                {scope}
              </span>
            </div>
            <div className="text-[11px] text-white/40 mt-1 flex items-center gap-3 flex-wrap">
              <span className="flex items-center gap-1">
                <Heart size={11} className="text-rose-300" />
                {status?.emotion || '未知情绪'}
              </span>
              <span className="font-mono truncate">
                会话 {currentSessionId || 'default_user'}
              </span>
            </div>
          </div>
          <button
            onClick={() => void refresh()}
            className="p-2 rounded-xl text-white/40 hover:text-white hover:bg-white/10 transition-colors shrink-0"
            title="刷新状态"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>

        {/* 指标 */}
        {metrics.length > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {metrics.map((metric) => {
              const ratio = Math.max(0, Math.min(1, metric.value / metric.max));
              return (
                <div
                  key={metric.key}
                  className="rounded-xl border border-white/5 bg-black/20 px-3 py-2"
                >
                  <div className="flex items-center justify-between text-[11px] text-white/45">
                    <span>{metric.label}</span>
                    <span className="font-mono">{metric.value.toFixed(0)}</span>
                  </div>
                  <div className="mt-1.5 h-1 rounded-full bg-white/5 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-emerald-400/70 to-sky-400/70"
                      style={{ width: `${ratio * 100}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {error && (
          <div className="text-[11px] text-amber-200/80 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
            {error}
          </div>
        )}

        {/* Tab 切换 */}
        <div className="flex items-center gap-1.5 p-1 rounded-xl bg-black/30 border border-white/5 w-fit">
          {TABS.map((item) => {
            const Icon = item.icon;
            const active = tab === item.key;
            return (
              <button
                key={item.key}
                onClick={() => setTab(item.key)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] transition-colors ${
                  active
                    ? 'bg-white/10 text-white border border-white/10'
                    : 'text-white/40 hover:text-white/70'
                }`}
              >
                <Icon size={12} />
                {item.label}
              </button>
            );
          })}
        </div>

        <div className="rounded-2xl border border-white/10 bg-black/20 p-5">
          {tab === 'activity' && (
            <ActivityControls
              scope={scope}
              conversationId={currentSessionId}
              status={status}
              onRefresh={() => void refresh()}
            />
          )}
          {tab === 'schedule' && <ScheduleTimeline status={status} />}
          {tab === 'settings' && (
            <RoleRuntimeSettings
              role={role}
              models={models}
              selectedModel={selectedModel}
              onSelectModel={onSelectModel}
            />
          )}
          {tab === 'worldline' && (
            <WorldlineTree
              scope={scope}
              personaFile={role?.persona_file}
              onRequestDelete={handleDeleteMemory}
            />
          )}
        </div>
      </div>
    </div>
  );
};

export default CompanionPanel;
