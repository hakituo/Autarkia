// @ts-check
// 看板入口：装配各模块并启动数据加载

import { $, closestButton, input, markActive } from './utils/dom.js';
import { fetchOverview, getStoredToken, saveStoredToken, syncPricing } from './api/tokenStatsApi.js';
import { getData, getState, patchState, setData } from './store/dashboardStore.js';
import { applyDateRange, applyPreset, initFilters, refreshFilterOptions, renderChips, resolveDrillRange } from './sections/filters.js';
import { renderKpis } from './components/statCards.js';
import { renderTokenChart } from './components/tokenChart.js';
import { renderRequestPanel } from './sections/requestPanel.js';
import { renderDistributions } from './sections/distributions.js';
import { renderCostPanel, markSyncing } from './sections/costPanel.js';
import { renderDetail, renderCoverage } from './sections/detail.js';
import { exportCsv } from './sections/exporter.js';

/**
 * 更新右上角状态文案
 * @param {string} text
 * @param {boolean} [isError]
 */
const setStatus = (text, isError = false) => {
  const status = $('status');
  status.className = isError ? 'status err' : 'status';
  status.textContent = text;
};

/**
 * 图表加载态
 * @param {boolean} loading
 */
const setLoading = (loading) => {
  ['chart-wrap', 'req-chart-wrap'].forEach((id) => {
    $(id).classList.toggle('loading', loading);
  });
};

/**
 * 按某个时间桶下钻
 * @param {string} key
 */
const drillDown = (key) => {
  const data = getData();
  const range = resolveDrillRange(key, data.granularity);
  applyDateRange(range.start, range.end);
  loadData();
};

/**
 * 渲染所有区块
 */
const renderAll = () => {
  const data = getData();
  const state = getState();
  renderChips();
  renderKpis(data);
  renderCostPanel(data);
  // 没价目表时成本曲线无从谈起，选项直接置灰
  const costBox = input('show-cost');
  costBox.disabled = !data.cost;
  if (costBox.disabled) patchState({ showCost: false });
  renderTokenChart(data, state.showRate, state.showCost, drillDown);
  renderRequestPanel(data, drillDown);
  renderDistributions(data);
  renderDetail(data);
  refreshFilterOptions(data);
  renderCoverage(data);
};

/**
 * 手动重抓一轮价格并刷新看板
 */
const syncPrices = async () => {
  markSyncing(true);
  setStatus('正在重抓价目表…');
  try {
    const { message } = await syncPricing();
    await loadData();
    setStatus(message + ' · ' + new Date().toLocaleTimeString('zh-CN'), message === '已同步' ? false : true);
  } catch (error) {
    setStatus('价格同步失败：' + error.message, true);
  } finally {
    markSyncing(false);
  }
};

/**
 * 拉取数据并重绘
 */
const loadData = async () => {
  setStatus('加载中…');
  setLoading(true);
  try {
    const data = await fetchOverview(getState());
    setData(data);
    renderAll();
    setStatus('更新于 ' + new Date().toLocaleTimeString('zh-CN'));
  } catch (error) {
    setStatus('加载失败：' + error.message, true);
  } finally {
    setLoading(false);
  }
};

/**
 * 绑定顶部操作与图表开关
 */
const bindEvents = () => {
  $('refresh').addEventListener('click', loadData);
  $('export').addEventListener('click', exportCsv);

  $('show-rate').addEventListener('change', () => {
    patchState({ showRate: input('show-rate').checked });
    renderTokenChart(getData(), getState().showRate, getState().showCost, drillDown);
  });

  $('show-cost').addEventListener('change', () => {
    patchState({ showCost: input('show-cost').checked });
    renderTokenChart(getData(), getState().showRate, getState().showCost, drillDown);
  });

  $('sync-pricing').addEventListener('click', syncPrices);

  $('detail-limit').addEventListener('click', (event) => {
    const btn = closestButton(event);
    if (!btn) return;
    patchState({ detailLimit: Number(btn.dataset.limit) });
    markActive($('detail-limit'), (item) => item === btn);
    renderDetail(getData());
  });

  $('token-toggle').addEventListener('click', () => {
    const bar = $('token-bar');
    bar.style.display = bar.style.display === 'none' ? 'block' : 'none';
  });

  $('token-save').addEventListener('click', () => {
    saveStoredToken(input('token').value.trim());
    loadData();
  });
};

/**
 * 启动看板
 */
const bootstrap = () => {
  input('token').value = getStoredToken();
  bindEvents();
  initFilters(loadData);
  // 默认视图：近 30 天
  applyPreset(getState().preset);
  loadData();
};

bootstrap();
