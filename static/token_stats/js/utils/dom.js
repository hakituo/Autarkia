// @ts-check
// DOM 工具：集中处理元素查询与创建，避免各模块重复写样板

/** SVG 命名空间 */
export const SVG_NS = 'http://www.w3.org/2000/svg';

/**
 * 按 id 取元素
 * @param {string} id
 * @returns {HTMLElement}
 */
export const $ = (id) => /** @type {HTMLElement} */ (document.getElementById(id));

/**
 * 按 id 取输入框
 * @param {string} id
 * @returns {HTMLInputElement}
 */
export const input = (id) => /** @type {HTMLInputElement} */ (document.getElementById(id));

/**
 * 按 id 取按钮
 * @param {string} id
 * @returns {HTMLButtonElement}
 */
export const button = (id) => /** @type {HTMLButtonElement} */ (document.getElementById(id));

/**
 * 按 id 取下拉框
 * @param {string} id
 * @returns {HTMLSelectElement}
 */
export const select = (id) => /** @type {HTMLSelectElement} */ (document.getElementById(id));

/**
 * 从事件里取最近的祖先按钮
 * @param {Event} event
 * @returns {HTMLElement | null}
 */
export const closestButton = (event) => /** @type {HTMLElement} */ (event.target).closest('button');

/**
 * 创建普通元素
 * @param {string} tag
 * @param {string} [className]
 * @param {string | number} [text]
 * @returns {HTMLElement}
 */
export const createEl = (tag, className, text) => {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined && text !== null) el.textContent = String(text);
  return el;
};

/**
 * 创建按钮元素
 * @param {string} [className]
 * @param {string} [text]
 * @returns {HTMLButtonElement}
 */
export const createButton = (className, text) => {
  const el = /** @type {HTMLButtonElement} */ (document.createElement('button'));
  el.type = 'button';
  if (className) el.className = className;
  if (text !== undefined && text !== null) el.textContent = String(text);
  return el;
};

/**
 * 创建 SVG 元素并批量写入属性
 * @param {string} tag
 * @param {Record<string, string | number>} [attrs]
 * @returns {SVGElement}
 */
export const createSvg = (tag, attrs = {}) => {
  const el = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, String(value)));
  return el;
};

/**
 * 选中一组按钮并切换 active 态
 * @param {HTMLElement | null} host
 * @param {(item: HTMLElement) => boolean} matcher
 */
export const markActive = (host, matcher) => {
  if (!host) return;
  [...host.children].forEach((item) => {
    const el = /** @type {HTMLElement} */ (item);
    el.classList.toggle('active', matcher(el));
  });
};
