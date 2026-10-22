import React, { useEffect, useMemo, useState } from 'react';
import { Check, Loader2, RefreshCw, ScanFace, Users } from 'lucide-react';
import { featureApi } from '../../api/featureApi';
import { useFeatureStore } from '../../store/useFeatureStore';
import RoleProfileEditor from '../conversations/RoleProfileEditor';

interface PersonaItem {
  filename: string;
  name?: string;
  role?: string;
  role_id?: string;
  default_model?: string;
  default_voice?: string;
}

interface PersonaSettingsTabProps {
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

/** 设置 - 人格：后端人设切换 + 角色昵称/头像/音色。 */
export const PersonaSettingsTab: React.FC<PersonaSettingsTabProps> = ({ onRequestConfirm }) => {
  const [personas, setPersonas] = useState<PersonaItem[]>([]);
  const [currentFile, setCurrentFile] = useState('');
  const [loading, setLoading] = useState(false);
  const [switching, setSwitching] = useState('');
  const [message, setMessage] = useState('');
  const [selectedScope, setSelectedScope] = useState('aveline');

  const roles = useFeatureStore((s) => s.roles);
  const loadRoles = useFeatureStore((s) => s.loadRoles);

  const load = async () => {
    setLoading(true);
    try {
      const [list, current] = await Promise.all([
        featureApi.listPersonas(),
        featureApi.getCurrentPersona().catch(() => null),
      ]);
      setPersonas(Array.isArray(list) ? list : []);
      setCurrentFile(String((current as any)?.filename || ''));
    } catch (error: any) {
      setMessage(error?.message || '人设列表加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    if (roles.length === 0) void loadRoles();
  }, []);

  const currentPersona = useMemo(
    () => personas.find((item) => item.filename === currentFile) || null,
    [personas, currentFile],
  );

  const handleSwitch = (persona: PersonaItem) => {
    const run = async () => {
      setSwitching(persona.filename);
      setMessage('');
      try {
        await featureApi.switchPersona(persona.filename);
        setCurrentFile(persona.filename);
        setMessage(`已切换为 ${persona.name || persona.filename}`);
      } catch (error: any) {
        setMessage(error?.message || '切换失败');
      } finally {
        setSwitching('');
      }
    };
    if (!onRequestConfirm) {
      void run();
      return;
    }
    onRequestConfirm({
      title: '切换人设',
      message: `将后端人设切换为「${persona.name || persona.filename}」，会立即影响之后的所有回复。确定切换？`,
      type: 'warning',
      confirmText: '切换',
      cancelText: '取消',
      onConfirm: () => void run(),
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium text-white/90 flex items-center gap-2">
          <ScanFace size={20} /> 人格
        </h3>
        <button
          onClick={() => void load()}
          className="p-1.5 rounded-lg text-white/40 hover:text-white hover:bg-white/10 transition-colors"
          title="刷新"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {message && (
        <div className="text-[11px] text-white/55 bg-white/5 border border-white/10 rounded-lg px-3 py-2">
          {message}
        </div>
      )}

      <div className="space-y-2">
        <div className="text-[11px] uppercase tracking-wider text-white/35">
          可用人设 {currentPersona ? `· 当前 ${currentPersona.name || currentPersona.filename}` : ''}
        </div>
        <div className="grid grid-cols-1 gap-2 max-h-64 overflow-y-auto custom-scrollbar pr-1">
          {personas.map((persona) => {
            const active = persona.filename === currentFile;
            return (
              <button
                key={persona.filename}
                onClick={() => handleSwitch(persona)}
                disabled={Boolean(switching)}
                className={`flex items-center justify-between px-3 py-2.5 rounded-xl border text-left transition-colors ${
                  active
                    ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-100'
                    : 'bg-black/20 border-white/5 text-white/60 hover:bg-black/40 hover:text-white'
                }`}
              >
                <span className="min-w-0">
                  <span className="block text-sm truncate">{persona.name || persona.filename}</span>
                  <span className="block text-[10px] font-mono text-white/30 truncate">
                    {persona.filename}
                    {persona.default_model ? ` · ${persona.default_model}` : ''}
                  </span>
                </span>
                {switching === persona.filename ? (
                  <Loader2 size={14} className="animate-spin shrink-0" />
                ) : active ? (
                  <Check size={14} className="shrink-0" />
                ) : null}
              </button>
            );
          })}
          {!loading && personas.length === 0 && (
            <div className="text-[11px] text-white/30 px-1 py-3">未读取到人设列表</div>
          )}
        </div>
      </div>

      <div className="space-y-3">
        <div className="text-[11px] uppercase tracking-wider text-white/35 flex items-center gap-1.5">
          <Users size={11} /> 角色资料（昵称 / 头像 / 音色）
        </div>
        <div className="flex flex-wrap gap-1.5">
          {roles.map((role) => (
            <button
              key={role.scope}
              onClick={() => setSelectedScope(role.scope)}
              className={`px-2.5 py-1 rounded-lg text-[11px] border transition-colors ${
                selectedScope === role.scope
                  ? 'bg-emerald-500/15 text-emerald-200 border-emerald-500/30'
                  : 'text-white/45 border-white/10 hover:text-white/80 hover:bg-white/5'
              }`}
            >
              {role.avatar || '🪐'} {role.display_name || role.name}
            </button>
          ))}
        </div>
        <div className="rounded-xl border border-white/10 bg-black/20 p-4">
          <RoleProfileEditor scope={selectedScope} />
        </div>
      </div>
    </div>
  );
};

export default PersonaSettingsTab;
