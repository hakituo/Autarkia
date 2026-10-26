// @ts-check
// 明细 CSV 导出

import { getData, getState } from '../store/dashboardStore.js';
import { localDate } from '../utils/format.js';

/** CSV 里成本列的表头与取数字段：导出裸数字，方便二次求和 */
const COST_COLUMNS = [
  ['成本', 'cost_total'],
  ['输入成本', 'cost_input'],
  ['命中读成本', 'cost_cache_read'],
  ['输出成本', 'cost_output'],
  ['已计价次数', 'cost_priced'],
];

/**
 * 把当前筛选下的时间序列导出成 CSV
 */
export const exportCsv = () => {
  const data = getData();
  const state = getState();
  if (!data) return;

  const costColumns = data.cost ? COST_COLUMNS : [];
  const head = ['时间', '请求数', '输入tokens', '缓存命中', '缓存未命中', '命中率', '输出tokens', '合计tokens']
    .concat(costColumns.map(([label]) => label));
  const lines = [head.join(',')];

  (data.series || []).forEach((row) => {
    const base = [
      row.key,
      row.requests,
      row.prompt_tokens,
      row.hit_tokens,
      row.miss_tokens,
      row.hit_rate === null ? '' : (row.hit_rate * 100).toFixed(2) + '%',
      row.completion_tokens,
      row.total_tokens,
    ];
    // 没价的桶写空而不是 0：导出去求和时 0 会被当成「真的没花钱」
    const costs = costColumns.map(([, field]) => (row[field] === null || row[field] === undefined ? '' : row[field]));
    lines.push(base.concat(costs).join(','));
  });

  const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `token-stats-${state.granularity}-${localDate()}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
};
