// @ts-check
// 用量数据接口封装：只负责取数与鉴权，不关心渲染

const API_ENDPOINT = '/api/v1/token-stats/overview';
const PRICING_ENDPOINT = '/api/v1/token-stats/pricing';
const TOKEN_STORAGE_KEY = 'tokenStatsToken';
const TOP_LIMIT = 30;

/**
 * 带鉴权的请求头
 * @returns {Record<string, string>}
 */
const authHeaders = () => {
  /** @type {Record<string, string>} */
  const headers = {};
  const token = getStoredToken();
  if (token) headers.Authorization = 'Bearer ' + token;
  return headers;
};

/**
 * 读取本地保存的访问令牌
 * @returns {string}
 */
export const getStoredToken = () => {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY) || '';
  } catch {
    return '';
  }
};

/**
 * 保存访问令牌到 localStorage
 * @param {string} token
 */
export const saveStoredToken = (token) => {
  try {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    // 隐私模式下 localStorage 不可写，忽略即可（看板仍可匿名访问）
  }
};

/**
 * 拼装查询参数
 * @param {{ granularity: string, start: string, end: string, model: string, provider: string }} state
 * @returns {URLSearchParams}
 */
export const buildOverviewQuery = (state) => {
  const params = new URLSearchParams({ granularity: state.granularity, top: String(TOP_LIMIT) });
  ['start', 'end', 'model', 'provider'].forEach((key) => {
    if (state[key]) params.set(key, state[key]);
  });
  return params;
};

/**
 * 发一次请求并校验统一响应包
 * @param {string} url
 * @param {{method?: string, headers?: Record<string, string>}} [options]
 * @returns {Promise<{status: string, data: any, message?: string}>}
 */
const requestPayload = async (url, options = {}) => {
  const resp = await fetch(url, { ...options, headers: authHeaders() });
  const payload = await resp.json();
  if (payload.status !== 'success') throw new Error(payload.message || '接口返回失败');
  return payload;
};

/**
 * 拉取一次看板数据
 * @param {object} state 当前筛选状态
 * @returns {Promise<object>} 后端返回的 data 字段
 */
export const fetchOverview = async (state) => {
  const payload = await requestPayload(`${API_ENDPOINT}?${buildOverviewQuery(state).toString()}`);
  return payload.data;
};

/**
 * 忽略缓存、立刻重抓一轮模型价格
 * @returns {Promise<{data: object, message: string}>} 价目表状态与后端提示
 */
export const syncPricing = async () => {
  const payload = await requestPayload(PRICING_ENDPOINT + '/sync', { method: 'POST' });
  return { data: payload.data, message: payload.message || '已同步' };
};

