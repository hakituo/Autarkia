// @ts-check
// 看板状态：筛选条件、排序规则与最近一次拉取到的数据

const DEFAULT_SORT = 'total_tokens';

/** 筛选与展示状态 */
const state = {
  granularity: 'day',
  start: '',
  end: '',
  model: '',
  provider: '',
  preset: '30d',
  showRate: false,
  showCost: false,
  detailLimit: 30,
};

/** 各表格独立的排序规则 */
/** @type {Record<string, { key: string, dir: 'asc' | 'desc' }>} */
const tableSort = {
  model: { key: DEFAULT_SORT, dir: 'desc' },
  source: { key: DEFAULT_SORT, dir: 'desc' },
  provider: { key: DEFAULT_SORT, dir: 'desc' },
  key: { key: DEFAULT_SORT, dir: 'desc' },
  channel: { key: DEFAULT_SORT, dir: 'desc' },
  detail: { key: 'key', dir: 'desc' },
};

/** 最近一次拉取到的数据 */
let data = null;

/**
 * 读取（可变引用）状态对象
 * @returns {object}
 */
export const getState = () => state;

/**
 * 合并状态
 * @param {Partial<typeof state>} patch
 */
export const patchState = (patch) => Object.assign(state, patch);

/**
 * 读取最近一次的数据
 * @returns {object | null}
 */
export const getData = () => data;

/**
 * 覆盖最近一次的数据
 * @param {object} value
 */
export const setData = (value) => {
  data = value;
};

/**
 * 读取某张表的排序规则
 * @param {'model' | 'source' | 'provider' | 'key' | 'channel' | 'detail'} table
 * @returns {{ key: string, dir: 'asc' | 'desc' }}
 */
export const getSort = (table) => tableSort[table];
