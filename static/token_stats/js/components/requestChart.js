// @ts-check
// API 请求次数趋势图：按时间桶展示调用量（面积 + 折线）

import { $, createSvg } from '../utils/dom.js';
import { bucketLabel, compact, fmt, num } from '../utils/format.js';
import { hideTooltip, moveTooltip, showTooltip } from './tooltip.js';

const LINE_COLOR = '#4c9aff';
const AXIS_COLOR = '#64707f';
const HEIGHT = 236;
const PAD = { left: 50, right: 14, top: 16, bottom: 28 };

/**
 * 渲染 API 请求次数趋势图
 * @param {object} data 后端返回的看板数据
 * @param {(key: string) => void} onDrillDown 点击柱子后的下钻回调
 */
export const renderRequestChart = (data, onDrillDown) => {
  const host = $('req-chart');
  host.replaceChildren();
  const series = data.series || [];
  const isMonth = data.granularity === 'month';

  if (!series.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = '当前筛选条件下没有数据';
    host.appendChild(empty);
    return;
  }

  const wrapWidth = $('req-chart-wrap').clientWidth || 560;
  const minStep = isMonth ? 28 : 9;
  const count = series.length;
  const avail = Math.max(120, wrapWidth - PAD.left - PAD.right);
  const step = Math.max(minStep, avail / count);
  const width = Math.max(wrapWidth - 2, PAD.left + PAD.right + step * count);
  const plotW = width - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const maxValue = Math.max(1, ...series.map((b) => num(b.requests)));

  const svg = createSvg('svg', {
    width, height: HEIGHT, viewBox: `0 0 ${width} ${HEIGHT}`,
  });

  // 面积渐变
  const defs = createSvg('defs');
  const gradient = createSvg('linearGradient', { id: 'reqAreaGradient', x1: 0, y1: 0, x2: 0, y2: 1 });
  gradient.appendChild(createSvg('stop', { offset: '0%', 'stop-color': LINE_COLOR, 'stop-opacity': 0.38 }));
  gradient.appendChild(createSvg('stop', { offset: '100%', 'stop-color': LINE_COLOR, 'stop-opacity': 0 }));
  defs.appendChild(gradient);
  svg.appendChild(defs);

  // 网格线与左轴刻度
  const gridCount = 4;
  for (let i = 0; i <= gridCount; i++) {
    const y = PAD.top + (plotH * i) / gridCount;
    svg.appendChild(createSvg('line', {
      x1: PAD.left, x2: width - PAD.right, y1: y, y2: y,
      stroke: i === gridCount ? '#2b3746' : '#1c2530',
    }));
    const label = createSvg('text', {
      x: PAD.left - 8, y: y + 4, 'text-anchor': 'end', fill: AXIS_COLOR, 'font-size': 10,
    });
    label.textContent = compact(Math.round(maxValue * (1 - i / gridCount)));
    svg.appendChild(label);
  }

  const points = series.map((bucket, index) => ({
    bucket,
    x: PAD.left + (index + 0.5) * step,
    y: PAD.top + plotH * (1 - num(bucket.requests) / maxValue),
  }));

  // 面积 + 折线
  const baseline = PAD.top + plotH;
  const areaD = `M ${points[0].x} ${baseline} ` +
    points.map((p) => `L ${p.x} ${p.y}`).join(' ') +
    ` L ${points[points.length - 1].x} ${baseline} Z`;
  svg.appendChild(createSvg('path', { d: areaD, fill: 'url(#reqAreaGradient)' }));
  svg.appendChild(createSvg('polyline', {
    points: points.map((p) => `${p.x},${p.y}`).join(' '),
    fill: 'none', stroke: LINE_COLOR, 'stroke-width': 2,
    'stroke-linejoin': 'round', 'stroke-linecap': 'round',
  }));

  // 数据点（桶数过多时省略，避免糊成一片）
  if (count <= 45) {
    points.forEach((p) => {
      svg.appendChild(createSvg('circle', {
        cx: p.x, cy: p.y, r: 2.4, fill: '#0b0f14', stroke: LINE_COLOR, 'stroke-width': 1.4,
      }));
    });
  }

  // 悬停竖线与高亮点
  const guide = createSvg('line', {
    class: 'hover-line', y1: PAD.top, y2: baseline, stroke: LINE_COLOR, 'stroke-width': 1, opacity: 0,
  });
  svg.appendChild(guide);
  const marker = createSvg('circle', {
    r: 4, fill: LINE_COLOR, stroke: '#0b0f14', 'stroke-width': 2, opacity: 0,
  });
  svg.appendChild(marker);

  const labelEvery = Math.max(1, Math.ceil(count / 12));
  points.forEach((p, index) => {
    if (index % labelEvery === 0) {
      const label = createSvg('text', {
        x: p.x, y: HEIGHT - PAD.bottom + 17, 'text-anchor': 'middle', fill: AXIS_COLOR, 'font-size': 10,
      });
      label.textContent = bucketLabel(p.bucket.key, data.granularity);
      svg.appendChild(label);
    }

    // 透明热区放在最后，保证 hover 优先级最高
    const hit = createSvg('rect', {
      x: p.x - step / 2, y: PAD.top, width: step, height: plotH, fill: 'transparent',
    });
    hit.addEventListener('mouseenter', (event) => {
      guide.setAttribute('x1', p.x);
      guide.setAttribute('x2', p.x);
      guide.setAttribute('opacity', '0.35');
      marker.setAttribute('cx', p.x);
      marker.setAttribute('cy', p.y);
      marker.setAttribute('opacity', '1');

      const requests = num(p.bucket.requests);
      const perCall = requests > 0 ? num(p.bucket.total_tokens) / requests : 0;
      showTooltip(event, {
        title: p.bucket.key + (isMonth ? '（月）' : ''),
        rows: [
          ['请求次数', fmt(requests)],
          ['输入', fmt(p.bucket.prompt_tokens)],
          ['输出', fmt(p.bucket.completion_tokens)],
          ['单次均耗', compact(Math.round(perCall)) + ' tokens'],
        ],
        footer: ['合计 tokens', fmt(p.bucket.total_tokens)],
      });
    });
    hit.addEventListener('mousemove', moveTooltip);
    hit.addEventListener('mouseleave', () => {
      guide.setAttribute('opacity', '0');
      marker.setAttribute('opacity', '0');
      hideTooltip();
    });
    hit.addEventListener('click', () => onDrillDown(p.bucket.key));
    svg.appendChild(hit);
  });

  host.appendChild(svg);
};
