// @ts-check
// 分布表：按模型 / 调用来源 / Provider / Key / 采购渠道

import { renderDataTable } from '../components/dataTable.js';
import { getSort } from '../store/dashboardStore.js';

/** 五张分布表的定义 */
const TABLES = [
  { table: 'table-model', sortKey: 'model', rows: 'by_model', label: '模型', showShare: true },
  { table: 'table-source', sortKey: 'source', rows: 'by_source', label: '调用来源' },
  { table: 'table-provider', sortKey: 'provider', rows: 'by_provider', label: 'Provider' },
  { table: 'table-key', sortKey: 'key', rows: 'by_key', label: 'Key' },
  { table: 'table-channel', sortKey: 'channel', rows: 'by_channel', label: '采购渠道' },
];

/**
 * 渲染单张分布表
 * @param {object} def 分布表定义
 * @param {object} data
 */
const renderOne = (def, data) => {
  renderDataTable({
    table: def.table,
    rows: data[def.rows] || [],
    label: def.label,
    sort: getSort(def.sortKey),
    onSort: () => renderOne(def, data),
    showShare: def.showShare,
    showCost: Boolean(data.cost),
    currency: data.cost ? data.cost.totals.currency : 'USD',
  });
};

/**
 * 渲染全部分布表
 * @param {object} data
 */
export const renderDistributions = (data) => {
  TABLES.forEach((def) => renderOne(def, data));
};
