// 会话归属角色与未读标记。
//
// 后端 sessions 只有 id/title/updated_at，没有角色字段，也没有已读状态。
// 角色归属按会话 ID 约定反解（与 core/utils/data/conversation_labels.py 的规则保持一致），
// 已读状态放 localStorage：只在「本地打开过之后又有更新」时显示未读徽章。

const READ_MARKERS_KEY = 'aveline_conversation_read_v1';

const PERSONA_TOKEN_TO_SCOPE: Record<string, string> = {
  core_aveline: 'aveline',
  aveline: 'aveline',
  aveline_qq: 'aveline',
  aveline_qq_master: 'aveline',
  aveline_qq_group: 'aveline',
  core_ling: 'ling',
  ling: 'ling',
  ling_qq: 'ling',
  ling_qq_love: 'ling',
  ling_qq_group: 'ling',
  ling: 'ling',
  qq_official_1: 'xiaolu',
  qq_official_2: 'yeye',
};

/** 从会话 ID 反解角色 scope；无法识别时返回 'unknown'。 */
export const resolveRoleScopeFromConversationId = (conversationId: string): string => {
  const cid = String(conversationId || '').trim().toLowerCase();
  if (!cid) return 'unknown';
  if (cid === 'default_user' || cid === 'default') return 'user';

  const personaMatch = cid.match(/__persona__([a-z0-9_]+)/);
  if (personaMatch) {
    const token = personaMatch[1];
    if (PERSONA_TOKEN_TO_SCOPE[token]) return PERSONA_TOKEN_TO_SCOPE[token];
    // 允许 core_xxx / xxx_qq 两种写法，剥掉前后缀后即为 scope
    const stripped = token.replace(/^core_/, '').replace(/_qq.*$/, '');
    return stripped || 'unknown';
  }

  if (cid.startsWith('web_')) {
    const scope = cid.slice(4).split('__')[0];
    return scope || 'unknown';
  }

  if (cid.startsWith('private_') || cid.startsWith('group_') || cid.startsWith('peer_')) {
    return 'unknown';
  }

  // 普通自定义会话默认归到主用户工作区
  return 'user';
};

/** 会话展示名：优先用后端 title，空标题给一个稳定的兜底。 */
export const conversationDisplayTitle = (title: string | undefined, id: string): string => {
  const text = String(title || '').trim();
  if (text) return text;
  return id === 'default_user' ? '主线对话' : '未命名话题';
};

const safeParse = (raw: string | null): Record<string, number> => {
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
};

export const loadReadMarkers = (): Record<string, number> => {
  try {
    return safeParse(localStorage.getItem(READ_MARKERS_KEY));
  } catch {
    return {};
  }
};

export const saveReadMarker = (conversationId: string, timestamp: number): void => {
  if (!conversationId) return;
  try {
    const markers = loadReadMarkers();
    const previous = Number(markers[conversationId] || 0);
    if (timestamp <= previous) return;
    markers[conversationId] = timestamp;
    localStorage.setItem(READ_MARKERS_KEY, JSON.stringify(markers));
  } catch {
    // 本地存储不可用时静默降级：不显示未读徽章，不影响聊天
  }
};

/** 会话是否有未读更新（本地打开时间早于最后更新时间）。 */
export const isConversationUnread = (
  updatedAt: number,
  conversationId: string,
  markers: Record<string, number>,
): boolean => {
  if (!updatedAt) return false;
  const lastRead = Number(markers[conversationId] || 0);
  if (!lastRead) return false; // 从未打开过的历史会话不算未读，避免首次进入全红
  return updatedAt > lastRead + 1;
};

export const relativeTime = (timestampSeconds: number): string => {
  const ts = Number(timestampSeconds || 0);
  if (!ts) return '';
  const ms = ts > 1e12 ? ts : ts * 1000;
  const diff = Date.now() - ms;
  if (diff < 60_000) return '刚刚';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`;
  const date = new Date(ms);
  return `${date.getMonth() + 1}-${String(date.getDate()).padStart(2, '0')}`;
};
