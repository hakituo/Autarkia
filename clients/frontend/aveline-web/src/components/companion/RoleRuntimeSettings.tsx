import React, { useState } from 'react';
import { Check, Cpu, Loader2, Mic2, ScanFace } from 'lucide-react';
import { featureApi } from '../../api/featureApi';
import type { Model } from '../../types';
import type { RoleProfile } from '../../types/features';

interface RoleRuntimeSettingsProps {
  role: RoleProfile | null;
  models: Model[];
  selectedModel: Model | null;
  onSelectModel: (model: Model) => void;
  onNotify?: (message: string) => void;
}

/** 角色级运行时设置：人设文件、模型偏好、音色。 */
export const RoleRuntimeSettings: React.FC<RoleRuntimeSettingsProps> = ({
  role,
  models,
  selectedModel,
  onSelectModel,
  onNotify,
}) => {
  const [switching, setSwitching] = useState(false);
  const [message, setMessage] = useState('');

  const llmModels = models.filter((model) =>
    ['llm', 'dashscope', 'openai', 'siliconflow'].includes(String(model.type)),
  );

  const applyPersona = async () => {
    if (!role?.persona_file || switching) return;
    setSwitching(true);
    setMessage('');
    try {
      await featureApi.switchPersona(role.persona_file);
      const text = `后端人设已切换为 ${role.persona_file}（全局生效，新消息开始使用）`;
      setMessage(text);
      onNotify?.(text);
    } catch (error: any) {
      setMessage(error?.message || '切换人设失败');
    } finally {
      setSwitching(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-white/10 bg-black/20 p-4 space-y-3">
        <div className="flex items-center gap-2 text-white/75 text-xs">
          <ScanFace size={13} className="text-emerald-300" /> 人设
        </div>
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="text-xs text-white/70 font-mono truncate">
              {role?.persona_file || '未登记'}
            </div>
            <div className="text-[10px] text-white/30 mt-0.5">
              切换会改变后端的当前人设，对全局生效
            </div>
          </div>
          <button
            onClick={() => void applyPersona()}
            disabled={!role?.persona_file || switching}
            className="px-3 py-1.5 rounded-lg bg-emerald-500/15 text-emerald-200 border border-emerald-500/25 hover:bg-emerald-500/25 text-[11px] disabled:opacity-40 transition-colors shrink-0"
          >
            {switching ? '切换中…' : '设为当前人设'}
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-white/10 bg-black/20 p-4 space-y-2">
        <div className="flex items-center gap-2 text-white/75 text-xs mb-1">
          <Cpu size={13} className="text-sky-300" /> 角色模型偏好
        </div>
        <div className="max-h-48 overflow-y-auto custom-scrollbar space-y-1 pr-1">
          {llmModels.map((model) => {
            const active = selectedModel?.id === model.id;
            return (
              <button
                key={model.id}
                onClick={() => onSelectModel(model)}
                className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-left transition-colors ${
                  active
                    ? 'bg-sky-500/15 text-sky-100 border border-sky-500/25'
                    : 'text-white/55 hover:bg-white/5 border border-transparent'
                }`}
              >
                <span className="min-w-0">
                  <span className="block text-xs truncate">{model.name}</span>
                  <span className="block text-[10px] font-mono text-white/25 truncate">
                    {model.type}
                  </span>
                </span>
                {active && <Check size={12} className="shrink-0" />}
              </button>
            );
          })}
          {llmModels.length === 0 && (
            <div className="text-[11px] text-white/30 px-1 py-2">没有可用模型</div>
          )}
        </div>
        <div className="text-[10px] text-white/25 leading-relaxed">
          选择结果按角色保存在本地，切换到该角色的会话时自动套用；发送消息时随请求带上。
        </div>
      </div>

      <div className="rounded-xl border border-white/10 bg-black/20 p-4 flex items-center justify-between">
        <div className="flex items-center gap-2 text-white/75 text-xs">
          <Mic2 size={13} className="text-amber-300" /> 音色
        </div>
        <span className="text-xs text-white/55 font-mono">
          {role?.voice_id || '跟随全局默认'}
        </span>
      </div>

      {message && (
        <div className="text-[11px] text-white/50 bg-white/5 border border-white/10 rounded-lg px-3 py-2 flex items-center gap-2">
          {switching && <Loader2 size={11} className="animate-spin" />}
          {message}
        </div>
      )}
    </div>
  );
};

export default RoleRuntimeSettings;
