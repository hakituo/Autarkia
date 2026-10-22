import React, { useEffect, useState } from 'react';
import {
  Download,
  HardDrive,
  Loader2,
  ShieldCheck,
  Trash2,
  UploadCloud,
  HeartHandshake,
  Flame,
} from 'lucide-react';
import { featureApi } from '../../api/featureApi';
import {
  clearLocalChatCache,
  exportLocalData,
  isDeviceContextEnabled,
  isLocalHistoryEnabled,
  setDeviceContextEnabled,
  setLocalHistoryEnabled,
} from '../../utils/privacyFlags';

interface PrivacySettingsTabProps {
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

const Toggle = ({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
}) => (
  <button
    onClick={() => onChange(!checked)}
    disabled={disabled}
    className={`w-12 h-6 rounded-full relative transition-colors duration-300 disabled:opacity-40 ${
      checked ? 'bg-emerald-600' : 'bg-white/10'
    }`}
    aria-pressed={checked}
  >
    <span
      className={`absolute top-1 left-1 w-4 h-4 bg-white rounded-full shadow-md transition-transform duration-300 ${
        checked ? 'translate-x-6' : 'translate-x-0'
      }`}
    />
  </button>
);

const Row = ({
  icon: Icon,
  label,
  description,
  children,
}: {
  icon: React.ElementType;
  label: string;
  description: string;
  children: React.ReactNode;
}) => (
  <div className="flex items-start justify-between gap-4 bg-black/20 border border-white/5 rounded-xl p-4">
    <div className="flex items-start gap-3 min-w-0">
      <div className="p-2 rounded-lg bg-white/5 text-white/50 shrink-0">
        <Icon size={15} />
      </div>
      <div className="min-w-0">
        <div className="text-sm text-white/80">{label}</div>
        <div className="text-[11px] text-white/40 mt-0.5 leading-relaxed">{description}</div>
      </div>
    </div>
    <div className="shrink-0">{children}</div>
  </div>
);

/** 设置 - 隐私：后端开关 + 本地留痕开关 + 数据管理。 */
export const PrivacySettingsTab: React.FC<PrivacySettingsTabProps> = ({ onRequestConfirm }) => {
  const [autoCare, setAutoCare] = useState(false);
  const [sensitive, setSensitive] = useState(false);
  const [localHistory, setLocalHistory] = useState(isLocalHistoryEnabled());
  const [deviceContext, setDeviceContextState] = useState(isDeviceContextEnabled());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [prefs, sensitiveStatus] = await Promise.all([
          featureApi.getPreferences().catch(() => ({})),
          featureApi.getSensitiveStatus().catch(() => ({})),
        ]);
        if (cancelled) return;
        setAutoCare(Boolean((prefs as any)?.active_care_enabled));
        setSensitive(Boolean((sensitiveStatus as any)?.enabled));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleAutoCare = async (value: boolean) => {
    setBusy('autoCare');
    setMessage('');
    try {
      await featureApi.updatePreferences({ active_care_enabled: value });
      setAutoCare(value);
      setMessage(value ? '已开启主动关怀' : '已关闭主动关怀');
    } catch (error: any) {
      setMessage(error?.message || '设置失败');
    } finally {
      setBusy('');
    }
  };

  const toggleSensitive = async (value: boolean) => {
    setBusy('sensitive');
    setMessage('');
    try {
      await featureApi.toggleSensitive(value);
      setSensitive(value);
      setMessage(value ? '分级模式已开启' : '分级模式已关闭');
    } catch (error: any) {
      setMessage(error?.message || '设置失败');
    } finally {
      setBusy('');
    }
  };

  const toggleLocalHistory = (value: boolean) => {
    const apply = () => {
      setLocalHistoryEnabled(value);
      setLocalHistory(value);
      if (!value) clearLocalChatCache();
      setMessage(value ? '聊天记录将保存在本机浏览器' : '已关闭本地留痕，并清空本地缓存');
    };
    if (value || !onRequestConfirm) {
      apply();
      return;
    }
    onRequestConfirm({
      title: '关闭本地留痕',
      message: '关闭后会立即清空浏览器里保存的聊天记录与草稿，确定继续？',
      type: 'warning',
      confirmText: '关闭并清空',
      cancelText: '取消',
      onConfirm: apply,
    });
  };

  const toggleDeviceContext = (value: boolean) => {
    setDeviceContextEnabled(value);
    setDeviceContextState(value);
    setMessage(value ? '已允许上报设备上下文' : '已停止上报设备上下文');
  };

  const clearCache = () => {
    const run = () => {
      clearLocalChatCache();
      setMessage('本地聊天缓存与草稿已清空，刷新后生效');
    };
    if (!onRequestConfirm) {
      run();
      return;
    }
    onRequestConfirm({
      title: '清空本地缓存',
      message: '会删除浏览器里的聊天记录、草稿与未读标记，服务端数据不受影响。确定继续？',
      type: 'danger',
      confirmText: '清空',
      cancelText: '取消',
      onConfirm: run,
    });
  };

  const exportData = () => {
    const json = exportLocalData();
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `aveline-local-data-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setMessage('已导出本地数据');
  };

  const clearServerMemories = async () => {
    setBusy('memories');
    try {
      await featureApi.clearMemories('short');
      setMessage('已清空服务端短期记忆');
    } catch (error: any) {
      setMessage(error?.message || '清空失败');
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="space-y-6">
      <h3 className="text-lg font-medium text-white/90 flex items-center gap-2">
        <ShieldCheck size={20} /> 隐私与数据
      </h3>

      {message && (
        <div className="text-[11px] text-white/55 bg-white/5 border border-white/10 rounded-lg px-3 py-2">
          {message}
        </div>
      )}

      <div className="space-y-3">
        <Row
          icon={HeartHandshake}
          label="主动关怀"
          description="允许角色在你不说话时主动发消息；关闭后只响应你的输入。"
        >
          <Toggle checked={autoCare} onChange={(v) => void toggleAutoCare(v)} disabled={loading || busy === 'autoCare'} />
        </Row>

        <Row
          icon={Flame}
          label="分级模式"
          description="开启后，敏感内容不会被隐私隔离规则排除在上下文之外。"
        >
          <Toggle checked={sensitive} onChange={(v) => void toggleSensitive(v)} disabled={loading || busy === 'sensitive'} />
        </Row>

        <Row
          icon={HardDrive}
          label="本地聊天记录"
          description="把聊天记录与草稿保存在本机浏览器，方便下次打开继续；关闭会立即清空。"
        >
          <Toggle checked={localHistory} onChange={toggleLocalHistory} />
        </Row>

        <Row
          icon={UploadCloud}
          label="设备上下文上报"
          description="上报电量、网络与应用使用时长，用于生理与环境感知。"
        >
          <Toggle checked={deviceContext} onChange={toggleDeviceContext} />
        </Row>
      </div>

      <div className="space-y-2">
        <div className="text-[11px] uppercase tracking-wider text-white/35">数据管理</div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <button
            onClick={exportData}
            className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white/70 hover:bg-white/10 text-xs transition-colors"
          >
            <Download size={14} /> 导出本地数据
          </button>
          <button
            onClick={clearCache}
            className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white/70 hover:bg-red-500/10 hover:text-red-200 text-xs transition-colors"
          >
            <Trash2 size={14} /> 清空本地缓存
          </button>
          <button
            onClick={() => void clearServerMemories()}
            disabled={busy === 'memories'}
            className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white/70 hover:bg-amber-500/10 hover:text-amber-200 text-xs transition-colors disabled:opacity-50"
          >
            {busy === 'memories' ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
            清空服务端短期记忆
          </button>
        </div>
        <p className="text-[10px] text-white/25 leading-relaxed">
          隐私隔离（sensitive 目录是否进入上下文）由后端配置 <code className="text-white/40">chat.privacy_isolation</code> 控制，
          客户端开关只影响本机留痕与上报行为。
        </p>
      </div>
    </div>
  );
};

export default PrivacySettingsTab;
