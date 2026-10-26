// @ts-check
// 通用数据表：分布表与时间明细表共用同一套表头、排序与单元格渲染

import { $, createEl } from '../utils/dom.js';
import { fmt, money, num, rateText } from '../utils/format.js';
import { sortRows, toggleSort } from '../utils/sort.js';
/** 表列定义：key 与后端字段一一对应，cost 列在价目表不可用时整列隐藏 */
export const COLUMNS = [
  { key: 'key', label: '维度', type: 'text' },
  { key: 'requests', label: '请求', type: 'num' },
  { key: 'prompt_tokens', label: '输入', type: 'num' },
  { key: 'hit_rate', label: '命中率', type: 'rate' },
  { key: 'completion_tokens', label: '输出', type: 'num' },
  { key: 'total_tokens', label: '合计', type: 'num' },
  { key: 'cost_total', label: '成本', type: 'money', isCost: true },
];

/**
 * 渲染命中率单元格（带迷你进度条）
 * @param {unknown} value
 * @returns {HTMLElement}
 */
const rateCell = (value) => {
  const td = createEl('td');
  const wrap = createEl('span', 'rate-wrap');
  const rate = typeof value === 'number' ? value : null;
  if (rate !== null) {
    const bar = createEl('i', 'rate-bar');
    bar.style.width = Math.max(4, Math.round(rate * 44)) + 'px';
    wrap.appendChild(bar);
    wrap.appendChild(document.createTextNode(rateText(rate)));
  } else {
    wrap.textContent = '-';
  }
  td.appendChild(wrap);
  return td;
};

/**
 * 渲染除首列以外的单元格
 * @param {{ key: string, type: string }} col
 * @param {Record<string, any>} row 数据行或合计行
 * @param {string} currency
 * @returns {HTMLElement}
 */
const cellOf = (col, row, currency) => {
  if (col.type === 'rate') return rateCell(row.hit_rate);
  if (col.type === 'money') {
    // 后端没价时给的是 null，必须原样显示「无价」，四舍五入成 0 会被读成「没花钱」
    if (row.cost_total === null || row.cost_total === undefined) {
      // 空桶（当天没有调用）不能叫「无价」，否则看着像漏了价格
      const empty = !num(row.requests);
      return createEl('td', 'money-cell none', empty ? '—' : '无价');
    }
    return createEl('td', 'money-cell', money(Number(row.cost_total), currency));
  }
  return createEl('td', null, fmt(row[col.key]));
};

/**
 * 渲染一张表
 * @param {object} options
 * @param {string} options.table 表格容器 id
 * @param {Array<Record<string, any>>} options.rows 数据行
 * @param {string} options.label 首列表头文案
 * @param {{ key: string, dir: 'asc' | 'desc' }} options.sort 排序规则（就地修改）
 * @param {() => void} options.onSort 排序变化后的重绘回调
 * @param {boolean} [options.showShare] 首列是否附加占比条
 * @param {boolean} [options.showCost] 是否显示成本列
 * @param {string} [options.currency] 成本币种
 * @param {{ label: string } & Record<string, any>} [options.footer] 合计行：按列 key 取数，避免位置错配
 */
export const renderDataTable = (options) => {
  const {
    table, rows, label, sort, onSort,
    showShare = false, showCost = false, currency = 'USD', footer,
  } = options;
  const host = $(table);
  host.replaceChildren();

  const columns = showCost ? COLUMNS : COLUMNS.filter((col) => !col.isCost);
  const maxTotal = Math.max(1, ...rows.map((r) => num(r.total_tokens)));

  const thead = createEl('thead');
  const headRow = createEl('tr');
  columns.forEach((col) => {
    const th = createEl('th');
    if (sort.key === col.key) th.classList.add('sorted');
    th.textContent = col.key === 'key' ? label : col.label;
    if (sort.key === col.key) {
      const arrow = createEl('span', 'arrow', sort.dir === 'asc' ? '↑' : '↓');
      th.appendChild(arrow);
    }
    th.onclick = () => {
      toggleSort(sort, col.key);
      onSort();
    };
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  host.appendChild(thead);

  const tbody = createEl('tbody');
  if (!rows.length) {
    const emptyRow = createEl('tr');
    const cell = /** @type {HTMLTableCellElement} */ (createEl('td', 'empty', '暂无数据'));
    cell.colSpan = columns.length;
    emptyRow.appendChild(cell);
    tbody.appendChild(emptyRow);
  }

  sortRows(rows, sort).forEach((row) => {
    const line = createEl('tr');
    const name = createEl('td', 'name-cell', String(row.key || '未标注'));
    if (showShare) {
      const bar = createEl('div', 'share-bar');
      bar.style.width = Math.round((num(row.total_tokens) / maxTotal) * 100) + '%';
      name.appendChild(bar);
    }
    line.appendChild(name);
    columns.slice(1).forEach((col) => line.appendChild(cellOf(col, row, currency)));
    tbody.appendChild(line);
  });
  host.appendChild(tbody);

  if (footer) {
    const tfoot = createEl('tfoot');
    const footRow = createEl('tr');
    footRow.appendChild(createEl('td', null, footer.label));
    columns.slice(1).forEach((col) => footRow.appendChild(cellOf(col, footer, currency)));
    tfoot.appendChild(footRow);
    host.appendChild(tfoot);
  }
};
