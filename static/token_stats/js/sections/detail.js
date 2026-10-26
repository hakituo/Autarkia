// @ts-check
// 时间明细表与数据覆盖说明

import { $, createEl } from '../utils/dom.js';
import { fmt, num } from '../utils/format.js';
import { renderDataTable } from '../components/dataTable.js';
import { getSort, getState } from '../store/dashboardStore.js';
import { sortRows } from '../utils/sort.js';

/**
 * 渲染时间明细表
 * @param {object} data
 */
export const renderDetail = (data) => {
  const state = getState();
  let rows = sortRows(data.series || [], getSort('detail'));
  if (state.detailLimit > 0) rows = rows.slice(0, state.detailLimit);

  renderDataTable({
    table: 'table-detail',
    rows,
    label: data.granularity === 'month' ? '月份' : '日期',
    sort: getSort('detail'),
    onSort: () => renderDetail(data),
    showShare: true,
    showCost: Boolean(data.cost),
    currency: data.cost ? data.cost.totals.currency : 'USD',
    footer: {
      label: '合计（当前筛选）',
      requests: data.totals.requests,
      prompt_tokens: data.totals.prompt_tokens,
      hit_rate: data.totals.hit_rate,
      completion_tokens: data.totals.completion_tokens,
      total_tokens: data.totals.total_tokens,
      cost_total: data.cost ? data.cost.totals.total : null,
    },
  });
};

/**
 * 渲染数据覆盖说明
 * @param {object} data
 */
export const renderCoverage = (data) => {
  const a = data.archive;
  const c = data.coverage;
  const missing = num(c.records) - num(c.with_completion);

  const host = $('coverage-note');
  host.replaceChildren();

  const note = createEl('div');
  const bits = [
    `<b>归档范围</b> ${(a.first_ts || '').slice(0, 10)} → ${(a.last_ts || '').slice(0, 10)}`,
    `<b>本次筛选</b> ${fmt(c.records)} 次调用`,
    `<b>输出 token 覆盖</b> ${fmt(c.with_completion)} 次`,
    `<b>有缓存字段</b> ${fmt(c.with_cache)} 次`,
  ];
  if (data.cost) {
    bits.push(`<b>已计价</b> ${fmt(data.cost.coverage.priced_requests)} / ${fmt(data.cost.coverage.requests)} 次`);
  }
  note.innerHTML = bits.join('　·　');
  host.appendChild(note);

  if (missing > 0) {
    const warn = createEl('div', 'warn',
      `另有 ${fmt(missing)} 次调用发生在输出 token 上线之前（或该 provider 未返回 usage），` +
      '看板对它们只统计输入侧，不按 0 计算。');
    warn.style.marginTop = '6px';
    host.appendChild(warn);
  }
};
