// @ts-check
// 日期选择器：点击弹出小日历，取代原生 date 输入框

import { $, closestButton, createButton, createEl } from '../utils/dom.js';
import { localDate } from '../utils/format.js';

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

let popup = null;
let context = { field: 'start', year: 0, month: 0, value: '' };
/** @type {(field: string, value: string) => void} */
let pickHandler = () => {};

/** 两位补零 */
const pad = (value) => String(value).padStart(2, '0');

/** 拼装 YYYY-MM-DD */
const formatDate = (year, month, day) => `${year}-${pad(month)}-${pad(day)}`;

/** 解析 YYYY-MM-DD */
const parseDate = (text) => {
  const [year, month, day] = String(text || '').split('-').map(Number);
  if (!year || !month || !day) return null;
  return { year, month, day };
};

/** 确保弹层存在（只创建一次，之后复用） */
const ensurePopup = () => {
  if (popup) return popup;
  popup = createEl('div', 'date-popup');
  popup.id = 'date-popup';
  document.body.appendChild(popup);
  document.addEventListener('click', (event) => {
    if (!popup.classList.contains('open')) return;
    if (popup.contains(event.target)) return;
    if (closestButton(event)?.classList.contains('date-btn')) return;
    closeDatePicker();
  });
  return popup;
};

/** 渲染日历网格 */
const renderGrid = (host, year, month, selected) => {
  host.replaceChildren();
  const startWeekday = new Date(year, month - 1, 1).getDay();
  const daysInMonth = new Date(year, month, 0).getDate();
  const prevMonthDays = new Date(year, month - 1, 0).getDate();

  for (let index = 0; index < 42; index++) {
    let day = index - startWeekday + 1;
    let cellMonth = month;
    let cellYear = year;
    let muted = false;

    if (day < 1) {
      day = prevMonthDays + day;
      cellMonth = month - 1;
      muted = true;
    } else if (day > daysInMonth) {
      day -= daysInMonth;
      cellMonth = month + 1;
      muted = true;
    }
    if (cellMonth === 0) {
      cellMonth = 12;
      cellYear -= 1;
    } else if (cellMonth === 13) {
      cellMonth = 1;
      cellYear += 1;
    }

    const cell = createButton('dp-cell', String(day));
    cell.dataset.date = formatDate(cellYear, cellMonth, day);
    if (muted) cell.classList.add('muted');
    if (selected && selected === cell.dataset.date) cell.classList.add('active');
    cell.onclick = () => pickDate(cell.dataset.date);
    host.appendChild(cell);
  }
};

/** 选中某一天并回调 */
const pickDate = (value) => {
  context.value = value;
  closeDatePicker();
  pickHandler(context.field, value);
};

/** 切换月份 */
const shiftMonth = (offset) => {
  let month = context.month + offset;
  let year = context.year;
  if (month < 1) {
    month = 12;
    year -= 1;
  } else if (month > 12) {
    month = 1;
    year += 1;
  }
  context.year = year;
  context.month = month;
  renderPopup();
};

/** 渲染弹层内容 */
const renderPopup = () => {
  const box = ensurePopup();
  box.replaceChildren();

  const head = createEl('div', 'dp-head');
  const prev = createButton('dp-nav', '‹');
  prev.onclick = () => shiftMonth(-1);
  const title = createEl('div', 'dp-title', `${context.year} 年 ${context.month} 月`);
  const next = createButton('dp-nav', '›');
  next.onclick = () => shiftMonth(1);
  head.append(prev, title, next);

  const week = createEl('div', 'dp-week');
  WEEKDAYS.forEach((name) => week.appendChild(createEl('span', null, name)));

  const grid = createEl('div', 'dp-grid');
  renderGrid(grid, context.year, context.month, context.value);

  const foot = createEl('div', 'dp-foot');
  const today = createButton('dp-mini', '今天');
  today.onclick = () => pickDate(localDate(0));
  const clear = createButton('dp-mini', '不限');
  clear.onclick = () => {
    context.value = '';
    closeDatePicker();
    pickHandler(context.field, '');
  };
  foot.append(today, clear);

  box.append(head, week, grid, foot);
};

/** 把弹层定位到锚点按钮附近 */
const positionPopup = (anchor) => {
  const box = ensurePopup();
  const rect = anchor.getBoundingClientRect();
  const scrollX = window.scrollX;
  const scrollY = window.scrollY;

  box.style.left = '0px';
  box.style.top = '0px';
  box.style.visibility = 'hidden';
  box.classList.add('open');

  const width = box.offsetWidth;
  const height = box.offsetHeight;
  let left = rect.left + scrollX;
  let top = rect.bottom + scrollY + 6;

  if (left + width > window.innerWidth - 12) left = window.innerWidth - width - 12;
  if (top + height > scrollY + window.innerHeight - 12) top = rect.top + scrollY - height - 6;

  box.style.left = Math.max(8, left) + 'px';
  box.style.top = Math.max(8, top) + 'px';
  box.style.visibility = '';
};

/**
 * 打开小日历
 * @param {'start' | 'end'} field 目标字段
 * @param {string} currentValue 当前值（YYYY-MM-DD 或空）
 * @param {(field: string, value: string) => void} onPick 选中回调
 */
export const openDatePicker = (field, currentValue, onPick) => {
  const box = ensurePopup();
  if (box.classList.contains('open')) {
    closeDatePicker();
    return;
  }
  const parsed = parseDate(currentValue) || parseDate(localDate(0));
  context = { field, year: parsed.year, month: parsed.month, value: currentValue || '' };
  pickHandler = onPick;
  renderPopup();
  positionPopup($(field));
};

/**
 * 关闭小日历
 */
export const closeDatePicker = () => {
  if (popup) popup.classList.remove('open');
};

/**
 * 刷新日期按钮上的文案
 * @param {'start' | 'end'} field
 * @param {string} value YYYY-MM-DD 或空
 */
export const setDateFieldLabel = (field, value) => {
  const btn = $(field);
  if (!btn) return;
  const text = btn.querySelector('.date-btn-text');
  if (text) text.textContent = value || '不限';
  btn.classList.toggle('filled', Boolean(value));
};
