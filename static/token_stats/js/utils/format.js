// @ts-check
// 数值与日期格式化：看板所有数字口径集中在这里

/**
 * 安全取数
 * @param {unknown} value
 * @returns {number}
 */
export const num = (value) => Number(value || 0);

/**
 * 千分位整数
 * @param {unknown} value
 * @returns {string}
 */
export const fmt = (value) => num(value).toLocaleString('zh-CN');

/**
 * 紧凑数字（万 / 十万 / 亿级缩写）
 * @param {unknown} value
 * @returns {string}
 */
export const compact = (value) => {
  const n = num(value);
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return String(n);
};

/**
 * 比率文本
 * @param {number | null | undefined} value
 * @returns {string}
 */
export const rateText = (value) => (value === null || value === undefined ? '-' : (value * 100).toFixed(1) + '%');

/**
 * 占比文本
 * @param {number} part
 * @param {number} total
 * @returns {string}
 */
export const percentText = (part, total) => (total > 0 ? (num(part) / total * 100).toFixed(1) + '%' : '-');

/** 币种符号；认不出来直接显示币种代码 */
const CURRENCY_SYMBOL = { USD: '$', CNY: '¥', RMB: '¥', EUR: '€' };

/**
 * 金额文本
 * @param {number | null | undefined} value 没有价时必须传 null，不能传 0
 * @param {string} [currency]
 * @param {number} [digits] 固定小数位（坐标轴用），省略则按量级自动放开
 * @returns {string}
 */
export const money = (value, currency = 'USD', digits) => {
  if (value === null || value === undefined) return '无价';
  const code = String(currency || 'USD').toUpperCase();
  const symbol = CURRENCY_SYMBOL[code] || code + ' ';
  // 单桶成本常见 0.0003 这种量级，固定两位会全渲染成 0，按大小放开小数位
  const n = num(value);
  const auto = Math.abs(n) >= 100 ? 0 : (Math.abs(n) >= 1 ? 2 : 4);
  return symbol + n.toLocaleString('zh-CN', { minimumFractionDigits: digits ?? auto, maximumFractionDigits: digits ?? auto });
};

/**
 * 「多久以前」文本，用于价目表同步时间
 * @param {unknown} seconds
 * @returns {string}
 */
export const agoText = (seconds) => {
  const s = num(seconds);
  if (s < 60) return '刚刚';
  if (s < 3600) return Math.floor(s / 60) + ' 分钟前';
  if (s < 86400) return Math.floor(s / 3600) + ' 小时前';
  return Math.floor(s / 86400) + ' 天前';
};

/**
 * 相对今天的日期（本地时区）
 * @param {number} [offsetDays]
 * @returns {string} YYYY-MM-DD
 */
export const localDate = (offsetDays = 0) => {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
};

/**
 * 当月第一天
 * @returns {string} YYYY-MM-DD
 */
export const monthStart = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`;
};

/**
 * 时间桶的展示标签
 * @param {unknown} key
 * @param {string} granularity
 * @returns {string}
 */
export const bucketLabel = (key, granularity) => (granularity === 'month' ? String(key) : String(key).slice(5));
