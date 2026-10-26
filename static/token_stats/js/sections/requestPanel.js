// @ts-check
// API 请求次数面板：指标条 + 调用趋势 + 来源排行

import { $, createEl } from '../utils/dom.js';
import { compact, fmt, num, percentText } from '../utils/format.js';
import { renderMiniStats } from '../components/statCards.js';
import { renderRequestChart } from '../components/requestChart.js';

/**
 * 汇总请求次数相关的派生指标
 * @param {object} data
 * @returns {{ total: number, average: number, peak: { key: string, requests: number }, perCall: number, buckets: number }}
 */
const buildRequestStats = (data) => {
  const series = data.series || [];
  const totals = data.totals || {};
  const total = num(totals.requests);
  const buckets = series.length || 1;

  let peak = { key: '', requests: 0 };
  series.forEach((bucket) => {
    if (num(bucket.requests) > peak.requests) {
      peak = { key: bucket.key, requests: num(bucket.requests) };
    }
  });

  return {
    total,
    average: total / buckets,
    peak,
    perCall: total > 0 ? num(totals.total_tokens) / total : 0,
    buckets,
  };
};

/**
 * 渲染请求来源排行（按调用次数）
 * @param {object} data
 */
const renderSourceRanking = (data) => {
  const host = $('req-sources');
  host.replaceChildren();

  const rows = [...(data.by_source || [])]
    .sort((a, b) => num(b.requests) - num(a.requests))
    .slice(0, 8);

  if (!rows.length) {
    host.appendChild(createEl('div', 'empty', '暂无数据'));
    return;
  }

  const max = Math.max(1, ...rows.map((row) => num(row.requests)));
  const total = num(data.totals.requests);

  rows.forEach((row) => {
    const requests = num(row.requests);
    const perCall = requests > 0 ? num(row.total_tokens) / requests : 0;

    const item = createEl('div', 'rank-item');
    const top = createEl('div', 'rank-top');
    const name = createEl('span', 'rank-name', row.key || '未标注');
    name.title = row.key || '未标注';
    top.append(name, createEl('span', 'rank-val', fmt(requests) + ' 次'));

    const bar = createEl('div', 'rank-bar');
    const fill = createEl('i');
    fill.style.width = Math.round((requests / max) * 100) + '%';
    bar.appendChild(fill);

    const meta = createEl('div', 'rank-meta',
      `占比 ${percentText(requests, total)} · 单次均耗 ${compact(Math.round(perCall))} tokens`);

    item.append(top, bar, meta);
    host.appendChild(item);
  });

  $('req-note').textContent = '按调用次数排序的 Top 8 来源；调用次数来自日志中的 source 字段，' +
    '同一来源的多次请求会合并计数。';
};

/**
 * 渲染整个请求次数面板
 * @param {object} data
 * @param {(key: string) => void} onDrillDown
 */
export const renderRequestPanel = (data, onDrillDown) => {
  const stats = buildRequestStats(data);
  const unit = data.granularity === 'month' ? '月' : '日';

  renderMiniStats([
    ['总请求数', fmt(stats.total), '当前筛选范围内的 API 调用', true],
    [`平均${unit}请求`, fmt(Math.round(stats.average)), `${stats.buckets} 个${unit}桶`],
    ['峰值', fmt(stats.peak.requests), stats.peak.key ? stats.peak.key + ' 最高' : '-'],
    ['单次均耗', compact(Math.round(stats.perCall)), '平均每次请求消耗的 tokens'],
  ]);

  renderRequestChart(data, onDrillDown);
  renderSourceRanking(data);

  $('req-hint').textContent = `共 ${stats.buckets} 个${unit}桶 · 合计 ${fmt(stats.total)} 次调用`;
};
