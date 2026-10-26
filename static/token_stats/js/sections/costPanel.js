// @ts-check
// 成本面板：成本构成、计价覆盖率、价目表健康度与待补价清单

import { $, button, createEl } from '../utils/dom.js';
import { agoText, fmt, money, num, rateText } from '../utils/format.js';

/** 成本四段：字段名与后端 cost.totals 的键一一对应 */
const SEGMENTS = [
  { key: 'input', label: '输入（未命中）', color: 'var(--cost-in)' },
  { key: 'cache_read', label: '缓存命中读', color: 'var(--cost-read)' },
  { key: 'cache_write', label: '缓存写入', color: 'var(--cost-write)' },
  { key: 'output', label: '输出', color: 'var(--cost-out)' },
];

/**
 * 堆叠条 + 逐项清单
 * @param {object} totals
 */
const renderComposition = (totals) => {
  const currency = totals.currency;
  const total = num(totals.total);
  const bar = $('cost-bar');
  const list = $('cost-list');
  bar.replaceChildren();
  list.replaceChildren();

  SEGMENTS.forEach((seg) => {
    const amount = totals[seg.key];
    if (amount === null || amount === undefined) return;
    const share = total > 0 ? num(amount) / total : 0;

    const slice = createEl('i');
    slice.style.width = (share * 100).toFixed(2) + '%';
    slice.style.background = seg.color;
    slice.title = `${seg.label} ${money(amount, currency)}`;
    bar.appendChild(slice);

    const row = createEl('div', 'cost-item');
    const dot = createEl('i');
    dot.style.background = seg.color;
    row.appendChild(dot);
    row.appendChild(createEl('span', null, seg.label));
    row.appendChild(createEl('span', 'amt', money(amount, currency)));
    row.appendChild(createEl('span', 'pct', (share * 100).toFixed(1) + '%'));
    list.appendChild(row);
  });

  if (!bar.children.length) {
    const placeholder = createEl('i');
    placeholder.style.width = '100%';
    placeholder.style.background = '#1c2632';
    bar.appendChild(placeholder);
  }
};

/**
 * 一级列表：用得最多的几个模型，各自当前的每 1M tokens 单价
 * @param {object} cost
 */
const renderModelPrices = (cost) => {
  const host = $('model-price-list');
  const rows = cost.models || [];
  host.replaceChildren();
  $('model-price-hint').textContent = rows.length
    ? `按调用次数取前 ${rows.length} 个 · 单价为每 1M tokens`
    : '这个区间没有可计价的调用';
  if (!rows.length) {
    host.appendChild(createEl('div', 'empty', '没有已计价的调用，价目表本身仍是最新的'));
    return;
  }
  rows.forEach((row) => {
    const per = row.per_1m || {};
    const parts = [['输入', per.input], ['命中', per.cache_read], ['写', per.cache_write], ['输出', per.output]]
      .filter(([, value]) => value !== null && value !== undefined)
      // 单价一律四位：同一行里 $0.3000 与 $1.20 混着写会像不同精度的数
      .map(([label, value]) => label + ' ' + money(value, row.currency, 4));
    const box = createEl('div', 'price-item');
    box.appendChild(createEl('span', 'name', row.model));
    box.appendChild(createEl('span', 'use', fmt(row.requests) + ' 次'));
    box.appendChild(createEl('span', 'amt money-cell', money(row.cost_total, row.currency)));
    const rates = createEl('span', 'rates', (parts.join(' · ') || '无单价') + (row.has_peak ? ' · 峰谷' : ''));
    rates.title = '价目键 ' + row.price_key + ' · 来源 ' + (row.source || '未标注');
    box.appendChild(rates);
    host.appendChild(box);
  });
};

/**
 * 价目表来源状态与待补价清单
 * @param {object} cost
 */
const renderPricing = (cost) => {
  const p = cost.pricing;
  const host = $('src-list');
  host.replaceChildren();

  const chip = (cls, text, title) => {
    const box = createEl('span', 'src ' + cls);
    box.appendChild(createEl('i', 'dot'));
    box.appendChild(document.createTextNode(text));
    if (title) box.title = title;
    return box;
  };

  host.appendChild(
    p.enabled === false
      ? chip('bad', '计价未启用', 'config/yaml/model_pricing.yaml 里 pricing.enabled = false')
      : chip('ok', `${fmt(p.entry_count)} 条价目`, p.snapshot),
  );
  Object.entries(p.sources || {}).forEach(([name, st]) => {
    const state = st.ok === true ? 'ok' : (st.skipped || st.ok === null ? 'skip' : 'bad');
    const suffix = st.ok === true ? `${fmt(st.entries)} 条` : (st.skipped ? '已停用' : '失败');
    host.appendChild(chip(state, `${name} · ${suffix}`, st.error || ''));
  });

  $('pricing-hint').textContent = p.stale
    ? '价目表已过期，建议同步'
    : '同步于 ' + agoText(p.age_seconds) + ' · 每 ' + Math.round(num(p.refresh_after_seconds) / 3600) + ' 小时自动更新';

  const gaps = cost.unpriced || [];
  const gapHost = $('gap-list');
  gapHost.replaceChildren();
  renderModelPrices(cost);
  $('gap-hint').textContent = gaps.length
    ? `${fmt(cost.coverage.unpriced_requests)} 次调用 / ${fmt(cost.coverage.unpriced_tokens)} tokens 未计价`
    : '全部调用都能计价';
  if (!gaps.length) {
    gapHost.appendChild(createEl('div', 'empty', '没有待补价模型'));
    return;
  }
  gaps.forEach((item) => {
    const box = createEl('div', 'gap-item');
    box.appendChild(createEl('span', 'name', item.model || '未标注'));
    box.appendChild(createEl('span', 'amt', `${fmt(item.requests)} 次 · ${fmt(item.prompt_tokens)} tokens`));
    box.appendChild(createEl('span', 'why', (item.channel ? item.channel + ' · ' : '') + item.reason));
    gapHost.appendChild(box);
  });
};

/**
 * 渲染成本面板
 * @param {object} data 后端返回的看板数据
 */
export const renderCostPanel = (data) => {
  const cost = data.cost;
  if (!cost) {
    $('cost-amount').textContent = '—';
    $('cost-sub').textContent = '价目表不可用，本次结果不计价';
    $('cost-bar').replaceChildren();
    $('cost-list').replaceChildren();
    $('cover-fill').style.width = '0%';
    $('cover-text').textContent = '—';
    $('cost-hint').textContent = '';
    $('cost-note').textContent = '价目表抓取失败或被禁用时，看板只显示 token 用量，不猜金额。';
    $('src-list').replaceChildren();
    $('model-price-list').replaceChildren();
    $('model-price-hint').textContent = '';
    $('gap-list').replaceChildren(createEl('div', 'empty', '价目表不可用'));
    $('gap-hint').textContent = '';
    return;
  }

  const t = cost.totals;
  const c = cost.coverage;
  $('cost-amount').textContent = money(t.total, t.currency);
  $('cost-sub').textContent = c.priced_requests
    ? `${fmt(c.priced_requests)} 次已计价调用 · 单次 ${money(c.priced_requests ? t.total / c.priced_requests : null, t.currency)}`
    : '没有可计价的调用';
  renderComposition(t);

  $('cover-fill').style.width = (num(c.priced_ratio) * 100).toFixed(1) + '%';
  $('cover-text').textContent = rateText(c.priced_ratio);
  $('cost-hint').textContent = t.currency === 'CNY' ? `按 ${t.usd_to_cny} 汇率折算` : '';

  const notes = [];
  if (c.unpriced_requests) {
    notes.push(`${fmt(c.unpriced_requests)} 次调用（${fmt(c.unpriced_tokens)} tokens）没有可用价格，未计入金额。`);
  }
  if (c.partial_requests) {
    notes.push(`${fmt(c.partial_requests)} 次调用只有部分字段有价，金额偏低。`);
  }
  notes.push('金额在读取时按当前价目表现算：改价或补价后，历史用量会跟着重算。');
  $('cost-note').textContent = notes.join(' ');

  renderPricing(cost);
};

/**
 * 同步按钮的忙碌态
 * @param {boolean} busy
 * @param {string} [text]
 */
export const markSyncing = (busy, text) => {
  const btn = button('sync-pricing');
  btn.disabled = busy;
  btn.textContent = busy ? '同步中…' : (text || '同步价格');
};
