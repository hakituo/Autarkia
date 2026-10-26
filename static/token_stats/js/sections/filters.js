// @ts-check
// 筛选区：时间预设、日期区间、粒度、模型与 Provider

import { $, closestButton, createEl, markActive, select } from '../utils/dom.js';
import { localDate, monthStart } from '../utils/format.js';
import { getData, getState, patchState } from '../store/dashboardStore.js';
import { openDatePicker, setDateFieldLabel } from '../components/datePicker.js';

const PRESET_NAMES = { today: '今天', '7d': '近 7 天', '30d': '近 30 天', month: '本月' };

/** 看板默认视图：近 30 天 */
export const DEFAULT_PRESET = '30d';

/** 重新拉取数据的回调，由入口注入 */
let reload = () => {};

/**
 * 高亮当前时间预设
 * @param {string} name
 */
export const markPreset = (name) => markActive($('presets'), (btn) => btn.dataset.preset === name);

/**
 * 预设对应的日期区间
 * @param {string} preset
 * @returns {{ start: string, end: string }}
 */
const presetRange = (preset) => {
  switch (preset) {
    case 'today':
      return { start: localDate(0), end: localDate(0) };
    case '7d':
      return { start: localDate(-6), end: localDate(0) };
    case '30d':
      return { start: localDate(-29), end: localDate(0) };
    case 'month':
      return { start: monthStart(), end: localDate(0) };
    default:
      return { start: '', end: '' };
  }
};

/**
 * 应用一个时间预设（同步状态与日期按钮文案）
 * @param {string} preset
 */
export const applyPreset = (preset) => {
  const range = presetRange(preset);
  patchState({ preset, start: range.start, end: range.end });
  setDateFieldLabel('start', range.start);
  setDateFieldLabel('end', range.end);
  markPreset(preset);
};

/**
 * 应用一个日期区间（供图表下钻复用）
 * @param {string} start
 * @param {string} end
 */
export const applyDateRange = (start, end) => {
  patchState({ start, end, preset: '' });
  setDateFieldLabel('start', start);
  setDateFieldLabel('end', end);
  markPreset('');
};

/**
 * 由时间桶 key 反推下钻区间
 * @param {string} key YYYY-MM-DD 或 YYYY-MM
 * @param {string} granularity
 * @returns {{ start: string, end: string }}
 */
export const resolveDrillRange = (key, granularity) => {
  if (granularity !== 'month') return { start: key, end: key };
  const [year, month] = key.split('-').map(Number);
  const lastDay = new Date(year, month, 0).getDate();
  return { start: key + '-01', end: key + '-' + String(lastDay).padStart(2, '0') };
};

/**
 * 渲染当前生效的筛选条件
 */
export const renderChips = () => {
  const data = getData();
  const state = getState();
  const f = data.filters;
  const chips = [];

  if (state.preset && state.preset !== 'all') {
    chips.push(['时间', PRESET_NAMES[state.preset] || state.preset]);
  } else if (f.start || f.end) {
    chips.push(['时间', (f.start || '最早') + ' → ' + (f.end || '最新')]);
  }
  if (f.model) chips.push(['模型', f.model]);
  if (f.provider) chips.push(['Provider', f.provider]);

  const host = $('chips');
  host.replaceChildren();
  chips.forEach(([label, value]) => {
    const chip = createEl('span', 'chip');
    chip.appendChild(createEl('span', null, label));
    chip.appendChild(createEl('b', null, value));

    const close = createEl('span', 'x', '×');
    close.title = '清除该项';
    close.onclick = () => {
      if (label === '模型') {
        patchState({ model: '' });
        select('model').value = '';
      } else if (label === 'Provider') {
        patchState({ provider: '' });
        select('provider').value = '';
      } else if (label === '时间') {
        patchState({ preset: 'all', start: '', end: '' });
        setDateFieldLabel('start', '');
        setDateFieldLabel('end', '');
        markPreset('all');
      }
      reload();
    };
    chip.appendChild(close);
    host.appendChild(chip);
  });
};

/**
 * 用后端返回的模型 / Provider 列表刷新下拉框
 * @param {object} data
 */
export const refreshFilterOptions = (data) => {
  const state = getState();
  const modelSelect = select('model');
  const providerSelect = select('provider');
  modelSelect.replaceChildren(new Option('全部模型', ''));
  providerSelect.replaceChildren(new Option('全部', ''));
  (data.options.models || []).forEach((name) => modelSelect.add(new Option(name, name)));
  (data.options.providers || []).forEach((name) => providerSelect.add(new Option(name, name)));
  modelSelect.value = state.model;
  providerSelect.value = state.provider;
};

/**
 * 选中某个日期后的处理：同步区间、保持起止有序并立即刷新
 * @param {'start' | 'end'} field
 * @param {string} value YYYY-MM-DD 或空
 */
const handleDatePick = (field, value) => {
  const state = getState();
  let start = state.start;
  let end = state.end;

  if (field === 'start') {
    start = value;
    if (end && start > end) end = start;
  } else {
    end = value;
    if (start && end < start) start = end;
  }

  patchState({ start, end, preset: '' });
  setDateFieldLabel('start', start);
  setDateFieldLabel('end', end);
  markPreset('');
  reload();
};

/**
 * 绑定筛选区交互
 * @param {() => void} reloadHandler 数据刷新回调
 */
export const initFilters = (reloadHandler) => {
  reload = reloadHandler;

  $('presets').addEventListener('click', (event) => {
    const btn = closestButton(event);
    if (!btn) return;
    applyPreset(btn.dataset.preset);
    reload();
  });

  $('granularity').addEventListener('click', (event) => {
    const btn = closestButton(event);
    if (!btn) return;
    patchState({ granularity: btn.dataset.value });
    markActive($('granularity'), (item) => item === btn);
    reload();
  });

  $('start').addEventListener('click', () => {
    openDatePicker('start', getState().start, handleDatePick);
  });

  $('end').addEventListener('click', () => {
    openDatePicker('end', getState().end, handleDatePick);
  });

  $('apply').addEventListener('click', () => {
    patchState({
      model: select('model').value,
      provider: select('provider').value,
      preset: '',
    });
    markPreset('');
    reload();
  });

  $('reset').addEventListener('click', () => {
    patchState({ model: '', provider: '' });
    select('model').value = '';
    select('provider').value = '';
    markActive($('granularity'), (item) => item.dataset.value === 'day');
    applyPreset(DEFAULT_PRESET);
    reload();
  });
};
