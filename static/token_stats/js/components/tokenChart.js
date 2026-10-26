// @ts-check
// 用量趋势图：按时间桶堆叠展示缓存命中 / 未命中 / 输出 token

import { $, createSvg } from '../utils/dom.js';
import { bucketLabel, compact, fmt, money, num, rateText } from '../utils/format.js';
import { hideTooltip, moveTooltip, showTooltip } from './tooltip.js';

const COLORS = { hit: '#34c759', miss: '#ff9f43', out: '#a78bfa', rate: '#4c9aff', cost: '#f2ce77' };
const HEIGHT = 330;
const PAD = { left: 60, right: 16, top: 14, bottom: 34 };
/** 右侧每条叠加曲线各占一条轴 */
const AXIS_BAND = 40;

/**
 * 坐标轴用的紧凑金额：轴标签上不要 0.1500 这种四位数
 * @param {number} value
 * @param {string} currency
 * @returns {string}
 */
const axisMoney = (value, currency) => money(Math.round(value * 100) / 100, currency, 2);

/**
 * 渲染 token 用量趋势图
 * @param {object} data 后端返回的看板数据
 * @param {boolean} showRate 是否叠加命中率曲线
 * @param {boolean} showCost 是否叠加成本曲线
 * @param {(key: string) => void} onDrillDown 点击柱子后的下钻回调
 */
export const renderTokenChart = (data, showRate, showCost, onDrillDown) => {
  const host = $('chart');
  host.replaceChildren();
  const series = data.series || [];
  const isMonth = data.granularity === 'month';
  const currency = data.cost ? data.cost.totals.currency : 'USD';
  // 价目表不可用时后端不给 cost 字段，叠加成本这条选项直接失效
  const costUsable = Boolean(data.cost) && series.some((b) => b.cost_total !== null && b.cost_total !== undefined);

  $('chart-hint').textContent =
    (isMonth ? '按月' : '按日') +
    ' · ' + (data.filters.start || (data.archive.first_ts || '').slice(0, 10)) +
    ' → ' + (data.filters.end || (data.archive.last_ts || '').slice(0, 10)) +
    ' · 点击柱子可下钻';

  if (!series.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = '当前筛选条件下没有数据';
    host.appendChild(empty);
    return;
  }

  const wrapWidth = $('chart-wrap').clientWidth || 900;
  const barW = isMonth ? 40 : 14;
  const gap = isMonth ? 26 : 9;
  const width = Math.max(wrapWidth - 4, series.length * (barW + gap) + 84);
  const pad = {
    ...PAD,
    right: PAD.right + (showRate ? AXIS_BAND : 0) + (showCost && costUsable ? AXIS_BAND : 0),
  };
  const plotW = width - pad.left - pad.right;
  const plotH = HEIGHT - pad.top - pad.bottom;
  const maxValue = Math.max(1, ...series.map((b) => num(b.hit_tokens) + num(b.miss_tokens) + num(b.completion_tokens)));
  const step = plotW / series.length;

  const svg = createSvg('svg', {
    width, height: HEIGHT, viewBox: `0 0 ${width} ${HEIGHT}`,
  });

  // 网格线与左轴刻度
  const gridCount = 4;
  for (let i = 0; i <= gridCount; i++) {
    const y = pad.top + (plotH * i) / gridCount;
    svg.appendChild(createSvg('line', {
      x1: pad.left, x2: width - pad.right, y1: y, y2: y,
      stroke: i === gridCount ? '#2b3746' : '#1c2530',
    }));
    const label = createSvg('text', {
      x: pad.left - 8, y: y + 4, 'text-anchor': 'end', fill: '#64707f', 'font-size': 10,
    });
    label.textContent = compact(maxValue * (1 - i / gridCount));
    svg.appendChild(label);
  }

  // 悬停高亮条
  const hover = createSvg('rect', {
    class: 'hover-line', y: pad.top, height: plotH, width: step, fill: '#4c9aff', opacity: 0,
  });
  svg.appendChild(hover);

  const labelEvery = Math.max(1, Math.ceil(series.length / 16));
  const centers = [];

  series.forEach((bucket, index) => {
    const left = pad.left + index * step;
    const x = left + (step - barW) / 2;
    const center = left + step / 2;
    centers.push(center);

    const group = createSvg('g', { class: 'bar-group' });

    // 透明热区：柱子再矮也能稳定 hover
    group.appendChild(createSvg('rect', {
      x: left, y: pad.top, width: step, height: plotH, fill: 'transparent',
    }));

    let y = pad.top + plotH;
    /** @type {Array<[number, string, string]>} */
    const segments = [
      [num(bucket.hit_tokens), COLORS.hit, 'bar-hit'],
      [num(bucket.miss_tokens), COLORS.miss, 'bar-miss'],
      [num(bucket.completion_tokens), COLORS.out, 'bar-out'],
    ];
    segments.forEach(([value, color, cls]) => {
      if (value <= 0) return;
      const h = Math.max(1, (value / maxValue) * plotH);
      y -= h;
      group.appendChild(createSvg('rect', {
        x, y, width: barW, height: h, fill: color, rx: 2, class: cls,
      }));
    });

    group.addEventListener('mouseenter', (event) => {
      /** @type {Array<[string, string, string?]>} */
      const rows = [
        ['请求', fmt(bucket.requests)],
        ['输入', fmt(bucket.prompt_tokens)],
        ['缓存命中', fmt(bucket.hit_tokens) + (bucket.hit_rate === null ? '' : ' (' + rateText(bucket.hit_rate) + ')'), COLORS.hit],
        ['缓存未命中', fmt(bucket.miss_tokens), COLORS.miss],
        ['输出', fmt(bucket.completion_tokens), COLORS.out],
      ];
      if (data.cost) {
        rows.push(['成本', money(bucket.cost_total, currency), COLORS.cost]);
      }
      showTooltip(event, {
        title: bucket.key + (isMonth ? '（月）' : ''),
        rows,
        footer: ['合计', fmt(bucket.total_tokens)],
      });
      hover.setAttribute('x', String(left));
      hover.setAttribute('width', String(step));
      hover.setAttribute('opacity', '0.08');
    });
    group.addEventListener('mousemove', moveTooltip);
    group.addEventListener('mouseleave', () => {
      hover.setAttribute('opacity', '0');
      hideTooltip();
    });
    group.addEventListener('click', () => onDrillDown(bucket.key));
    svg.appendChild(group);

    if (index % labelEvery === 0) {
      const label = createSvg('text', {
        x: center, y: HEIGHT - pad.bottom + 18, 'text-anchor': 'middle', fill: '#64707f', 'font-size': 10,
      });
      label.textContent = bucketLabel(bucket.key, data.granularity);
      svg.appendChild(label);
    }
  });

  /**
   * 画一条右轴叠加曲线
   * @param {(bucket: Record<string, any>) => number | null} valueOf 取值，null 表示该桶没有这项
   * @param {number} ceiling 轴顶值
   * @param {string} color
   * @param {(v: number) => string} format 轴刻度文案
   * @param {number} offset 距绘图区右端；两条轴要错开
   */
  const addOverlay = (valueOf, ceiling, color, format, offset) => {
    if (!(ceiling > 0)) return;
    const points = series
      .map((b, i) => {
        const value = valueOf(b);
        if (value === null || value === undefined) return null;
        return `${centers[i]},${pad.top + plotH * (1 - Math.min(1, value / ceiling))}`;
      })
      .filter(Boolean);
    if (points.length < 2) return;
    svg.appendChild(createSvg('polyline', {
      points: points.join(' '), fill: 'none', stroke: color, 'stroke-width': 1.6, opacity: 0.85,
    }));
    [0, 0.5, 1].forEach((ratio) => {
      const text = createSvg('text', {
        x: width - pad.right + offset, y: pad.top + plotH * (1 - ratio) + 4, fill: color, 'font-size': 10,
      });
      text.textContent = format(ceiling * ratio);
      svg.appendChild(text);
    });
  };

  // 命中率叠加曲线
  if (showRate) {
    addOverlay((b) => b.hit_rate, 1, COLORS.rate, (v) => Math.round(v * 100) + '%', 8);
  }
  // 成本叠加曲线：左轴是 token，成本量级差几个数量级，只能另开一条右轴
  if (showCost && costUsable) {
    addOverlay(
      (b) => b.cost_total,
      Math.max(...series.map((b) => num(b.cost_total))),
      COLORS.cost,
      (v) => axisMoney(v, currency),
      showRate ? AXIS_BAND + 6 : 8,
    );
  }

  host.appendChild(svg);

  $('chart-note').textContent =
    `共 ${series.length} 个${isMonth ? '月' : '日'}桶；` +
    '柱子自下而上依次为缓存命中、未命中、输出 token；悬停查看单桶明细，点击按该' +
    (isMonth ? '月' : '日') + '下钻。' +
    (showCost && !costUsable ? ' 当前筛选里没有可计价的桶，成本曲线暂无数据。' : '');
};
