// @ts-check
// 排序工具：表格按列排序的统一口径

import { num } from './format.js';

/**
 * 按当前排序列对数据行排序（不修改原数组）
 * @param {Array<Record<string, any>>} rows
 * @param {{ key: string, dir: 'asc' | 'desc' }} sort
 * @returns {Array<Record<string, any>>}
 */
export const sortRows = (rows, sort) => {
  const factor = sort.dir === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    if (sort.key === 'key') return factor * String(a.key).localeCompare(String(b.key));
    return factor * (num(a[sort.key]) - num(b[sort.key]));
  });
};

/**
 * 点击表头时切换排序方向
 * @param {{ key: string, dir: 'asc' | 'desc' }} sort
 * @param {string} key
 */
export const toggleSort = (sort, key) => {
  if (sort.key === key) {
    sort.dir = sort.dir === 'asc' ? 'desc' : 'asc';
    return;
  }
  sort.key = key;
  sort.dir = 'desc';
};
