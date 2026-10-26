// @ts-check
// 悬浮提示框：趋势图与请求次数图共用

import { $, createEl } from '../utils/dom.js';

const PADDING = 14;

/**
 * 追加若干「名称 / 数值」行
 * @param {HTMLElement} host
 * @param {Array<[string, string, string?]>} rows 第三项为可选颜色
 */
export const appendRows = (host, rows) => {
  rows.forEach(([label, value, color]) => {
    const row = createEl('div', 'tt-row');
    const key = createEl('span', 'k');
    if (color) {
      const dot = createEl('i', 'tt-dot');
      dot.style.background = color;
      key.appendChild(dot);
    }
    key.appendChild(document.createTextNode(label));
    const val = createEl('span', 'v', value);
    row.append(key, val);
    host.appendChild(row);
  });
};

/**
 * 展示提示框
 * @param {MouseEvent} event
 * @param {{ title: string, rows: Array<[string, string, string?]>, footer?: [string, string] }} payload
 */
export const showTooltip = (event, payload) => {
  const tt = $('tooltip');
  tt.replaceChildren();

  if (payload.title) tt.appendChild(createEl('div', 'tt-title', payload.title));
  appendRows(tt, payload.rows || []);

  if (payload.footer) {
    tt.appendChild(createEl('div', 'tt-sep'));
    const total = createEl('div', 'tt-row tt-total');
    total.append(createEl('span', 'k', payload.footer[0]), createEl('span', 'v', payload.footer[1]));
    tt.appendChild(total);
  }

  tt.classList.add('show');
  moveTooltip(event);
};

/**
 * 跟随鼠标移动提示框
 * @param {MouseEvent} event
 */
export const moveTooltip = (event) => {
  const tt = $('tooltip');
  const rect = tt.getBoundingClientRect();
  let x = event.clientX + PADDING;
  let y = event.clientY + PADDING;
  if (x + rect.width > window.innerWidth - 8) x = event.clientX - rect.width - PADDING;
  if (y + rect.height > window.innerHeight - 8) y = event.clientY - rect.height - PADDING;
  tt.style.left = x + 'px';
  tt.style.top = y + 'px';
};

/**
 * 隐藏提示框
 */
export const hideTooltip = () => {
  $('tooltip').classList.remove('show');
};
