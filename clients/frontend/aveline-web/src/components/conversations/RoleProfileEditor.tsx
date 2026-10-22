import React, { useEffect, useMemo, useState } from 'react';
import { Check, Loader2, Mic2, Save, UserRound } from 'lucide-react';
import { featureApi } from '../../api/featureApi';
import { useFeatureStore } from '../../store/useFeatureStore';
import type { RoleProfile } from '../../types/features';

interface RoleProfileEditorProps {
  scope: string;
  /** 展示用兜底名（角色清单还没加载完时用） */
  fallbackName?: string;
  onSaved?: (role: RoleProfile | null) => void;
}

const AVATAR_PRESETS = ['🌙', '🎧', '🌿', '🔥', '🐈', '🍵', '✨', '🖤'];

/** 角色昵称 / 头像 / 音色编辑。改动落到 /api/v1/roles/{scope}。 */
export const RoleProfileEditor: React.FC<RoleProfileEditorProps> = ({
  scope,
  fallbackName,
  onSaved,
}) => {
  const roles = useFeatureStore((s) => s.roles);
  const saveRole = useFeatureStore((s) => s.saveRole);
  const profile = useMemo(
    () => roles.find((role) => role.scope === scope) || null,
    [roles, scope],
  );

  const [displayName, setDisplayName] = useState('');
  const [avatar, setAvatar] = useState('');
  const [voiceId, setVoiceId] = useState('');
  const [voices, setVoices] = useState<Array<{ id: string; name: string }>>([]);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState(0);

  useEffect(() => {
    setDisplayName(profile?.display_name || profile?.name || fallbackName || '');
    setAvatar(profile?.avatar || '');
    setVoiceId(profile?.voice_id || '');
  }, [profile?.scope, profile?.display_name, profile?.avatar, profile?.voice_id, fallbackName]);

  useEffect(() => {
    let cancelled = false;
    featureApi
      .listVoices()
      .then((list) => {
        if (!cancelled) setVoices(list);
      })
      .catch(() => {
        if (!cancelled) setVoices([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSave = async () => {
    if (!scope || saving) return;
    setSaving(true);
    const ok = await saveRole(scope, {
      display_name: displayName.trim(),
      avatar: avatar.trim(),
      voice_id: voiceId.trim(),
    });
    setSaving(false);
    if (ok) {
      setSavedAt(Date.now());
      onSaved?.(useFeatureStore.getState().roles.find((r) => r.scope === scope) || null);
    }
  };

  if (!profile) {
    return (
      <div className="text-xs text-white/40 p-4 border border-white/5 rounded-xl bg-black/20">
        角色 <span className="font-mono text-white/60">{scope}</span> 不在后端角色清单里，
        暂时无法编辑昵称与音色。
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="w-12 h-12 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center text-2xl">
          {avatar || profile.avatar || <UserRound size={18} className="text-white/40" />}
        </div>
        <div className="min-w-0">
          <div className="text-sm text-white/90 truncate">
            {displayName || profile.display_name || profile.name}
          </div>
          <div className="text-[11px] font-mono text-white/35 truncate">
            scope: {profile.scope} · {profile.persona_file}
          </div>
        </div>
      </div>

      <label className="block space-y-1.5">
        <span className="text-[11px] uppercase tracking-wider text-white/40">昵称</span>
        <input
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          maxLength={40}
          className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-white outline-none focus:border-emerald-500/60"
          placeholder="显示在会话列表里的名字"
        />
      </label>

      <label className="block space-y-1.5">
        <span className="text-[11px] uppercase tracking-wider text-white/40">头像</span>
        <div className="flex items-center gap-2">
          <input
            value={avatar}
            onChange={(event) => setAvatar(event.target.value)}
            maxLength={512}
            className="flex-1 bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-white outline-none focus:border-emerald-500/60"
            placeholder="emoji 或图片 URL"
          />
          <div className="flex gap-1">
            {AVATAR_PRESETS.slice(0, 5).map((preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => setAvatar(preset)}
                className="w-8 h-8 rounded-lg bg-white/5 hover:bg-white/10 text-base transition-colors"
                title={`使用 ${preset}`}
              >
                {preset}
              </button>
            ))}
          </div>
        </div>
      </label>

      <label className="block space-y-1.5">
        <span className="text-[11px] uppercase tracking-wider text-white/40 flex items-center gap-1.5">
          <Mic2 size={11} /> 音色
        </span>
        <select
          value={voiceId}
          onChange={(event) => setVoiceId(event.target.value)}
          className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-white outline-none focus:border-emerald-500/60"
        >
          <option value="">跟随全局默认</option>
          {voices.map((voice) => (
            <option key={voice.id} value={voice.id}>
              {voice.name}
            </option>
          ))}
          {voiceId && !voices.some((voice) => voice.id === voiceId) && (
            <option value={voiceId}>{voiceId}（已下线）</option>
          )}
        </select>
      </label>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500/15 text-emerald-200 border border-emerald-500/30 hover:bg-emerald-500/25 transition-colors text-sm disabled:opacity-50"
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          保存资料
        </button>
        {savedAt > 0 && Date.now() - savedAt < 4000 && (
          <span className="text-xs text-emerald-300/80 flex items-center gap-1">
            <Check size={12} /> 已保存
          </span>
        )}
      </div>
    </div>
  );
};

export default RoleProfileEditor;
