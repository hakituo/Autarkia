// 网页端本地隐私开关。
//
// 后端侧真正生效的隐私能力有两处：主动关怀开关（system/preferences）与
// 分级模式（plugins/sensitive）。其余「是否把聊天记录留在浏览器」「是否上报
// 设备上下文」属于客户端行为，只能在前端拦，因此集中在这里读写，
// 由 useStore / Aveline 的副作用统一判断。

const LOCAL_HISTORY_KEY = 'aveline_privacy_local_history';
const DEVICE_CONTEXT_KEY = 'aveline_privacy_device_context';

const readFlag = (key: string, fallback: boolean): boolean => {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    return raw === 'on';
  } catch {
    return fallback;
  }
};

const writeFlag = (key: string, value: boolean): void => {
  try {
    localStorage.setItem(key, value ? 'on' : 'off');
  } catch {
    // 隐私模式下 localStorage 可能不可写，忽略即可
  }
};

/** 是否允许把聊天记录写入浏览器本地存储（默认开）。 */
export const isLocalHistoryEnabled = (): boolean => readFlag(LOCAL_HISTORY_KEY, true);
export const setLocalHistoryEnabled = (enabled: boolean): void =>
  writeFlag(LOCAL_HISTORY_KEY, enabled);

/** 是否允许上报设备上下文（电量/网络/使用时长，默认开）。 */
export const isDeviceContextEnabled = (): boolean => readFlag(DEVICE_CONTEXT_KEY, true);
export const setDeviceContextEnabled = (enabled: boolean): void =>
  writeFlag(DEVICE_CONTEXT_KEY, enabled);

/** 清空浏览器里保存的聊天记录与草稿。 */
export const clearLocalChatCache = (): void => {
  try {
    localStorage.removeItem('aveline_chat_history_v2');
    localStorage.removeItem('aveline_drafts_v1');
    localStorage.removeItem('aveline_conversation_read_v1');
  } catch {
    // 忽略
  }
};

/** 导出浏览器本地数据（聊天记录、草稿、设置）。 */
export const exportLocalData = (): string => {
  const keys = [
    'aveline_chat_history_v2',
    'aveline_drafts_v1',
    'aveline_settings_v1',
    'aveline_conversation_read_v1',
  ];
  const payload: Record<string, unknown> = { exported_at: new Date().toISOString() };
  keys.forEach((key) => {
    try {
      const raw = localStorage.getItem(key);
      payload[key] = raw ? JSON.parse(raw) : null;
    } catch {
      payload[key] = null;
    }
  });
  return JSON.stringify(payload, null, 2);
};
