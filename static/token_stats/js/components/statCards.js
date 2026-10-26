// @ts-check
// 指标卡：顶部 KPI 与请求次数面板的指标条

import { $, createEl } from '../utils/dom.js';
import { fmt, money, rateText } from '../utils/format.js';

/**
 * 渲染单个 KPI 卡
 * @param {string} modifier 颜色修饰（hit / miss / out / cost / 空）
 * @param {string} label
 * @param {string} value
 * @param {string} [sub]
 * @returns {HTMLElement}
 */
const kpiCard = (modifier, label, value, sub) => {
  const box = createEl('div', 'kpi ' + (modifier || ''));
  box.appendChild(createEl('div', 'label', label));
  box.appendChild(createEl('div', 'value', value));
  box.appendChild(createEl('div', 'sub', sub || ''));
  return box;
};

/**
 * 成本两张卡；价目表不可用时整块不出现，宁可没有钱也不能显示 0 元
 * @param {object} data
 * @returns {Array<HTMLElement>}
 */
const costCards = (data) => {
  const cost = data.cost;
  if (!cost) return [];
  const t = cost.totals;
  const c = cost.coverage;
  const avg = c.priced_requests > 0 && t.total !== null ? t.total / c.priced_requests : null;
  const hint = `计价 ${fmt(c.priced_requests)} / ${fmt(c.requests)} 次（${rateText(c.priced_ratio)}）`;
  return [
    kpiCard(
      'cost' + (t.total === null ? ' no-price' : ''),
      '成本合计',
      money(t.total, t.currency),
      t.total === null ? '价目表里没有这些模型' : `${hint}；无价 ${fmt(c.unpriced_tokens)} tokens`,
    ),
    kpiCard('cost', '每次请求均价', money(avg, t.currency), `峰时段 ${fmt(c.peak_requests)} 次调用`),
  ];
};

/**
 * 渲染顶部 KPI 区
 * @param {object} data 后端返回的看板数据
 */
export const renderKpis = (data) => {
  const t = data.totals;
  const c = data.coverage;
  $('kpis').replaceChildren(
    ...costCards(data),
    kpiCard('', 'API 请求数', fmt(t.requests), '筛选范围内调用次数'),
    kpiCard('', '输入 tokens', fmt(t.prompt_tokens), 'prompt_tokens 合计'),
    kpiCard('hit', '缓存命中', fmt(t.hit_tokens), '命中率 ' + rateText(t.hit_rate)),
    kpiCard('miss', '缓存未命中', fmt(t.miss_tokens), '首次写缓存也计在这里'),
    kpiCard('out', '输出 tokens', fmt(t.completion_tokens), `覆盖 ${fmt(c.with_completion)} / ${fmt(c.records)} 次调用`),
    kpiCard('', '合计 tokens', fmt(t.total_tokens), '输入 + 已记录输出'),
  );
};

/**
 * 渲染指标条（请求次数面板顶部）
 * @param {Array<[string, string, string?, boolean?]>} items 标签、值、副文案、是否高亮
 */
export const renderMiniStats = (items) => {
  const host = $('req-stats');
  host.replaceChildren();
  items.forEach(([label, value, sub, accent]) => {
    const box = createEl('div', 'mini-stat' + (accent ? ' accent' : ''));
    box.appendChild(createEl('div', 'label', label));
    box.appendChild(createEl('div', 'value', value));
    box.appendChild(createEl('div', 'sub', sub || ''));
    host.appendChild(box);
  });
};
