/**
 * compare.js — 环比 / 同比纯函数
 * 所有函数均为无副作用纯函数，可独立单测。
 *
 * 规则：
 * 1. 率类（unit 为 % 或 ‰）差值用「百分点 / pp」，禁止写成 %；
 *    比值类（unit 为空）用绝对差 + 变化率。
 * 2. 方向感知：读取 direction，lower_better 下降 = 改善。
 * 3. 同比缺失时返回 null，禁止用 0 或本期值兜底。
 * 4. 分母 < 30 加 smallSample 标记。
 * 5. 百分比保留 1 位小数，比值保留 2 位，绝对值整数。
 */

import { INDICATORS } from '../config/indicators.js';

/**
 * 获取指标的 direction 配置
 * @param {string} code
 * @returns {'higher_better'|'lower_better'|'range'}
 */
export function getDirection(code) {
  const ind = INDICATORS.find(i => i.code === code);
  return ind?.direction || 'higher_better';
}

/**
 * 判断指标是否为率类（unit 为 % 或 ‰）
 * @param {string} code
 * @returns {boolean}
 */
export function isRateType(code) {
  const ind = INDICATORS.find(i => i.code === code);
  return ind?.unit === '%' || ind?.unit === '‰';
}

/**
 * 获取指标单位
 * @param {string} code
 * @returns {string}
 */
export function getUnit(code) {
  const ind = INDICATORS.find(i => i.code === code);
  return ind?.unit || '';
}

/**
 * 环比：本期 vs 上一期
 * @param {string} code 指标码
 * @param {Object} trend { code: [月度值...] }
 * @param {string[]} months ['2026-01', '2026-02', ...]
 * @param {number} [denominator] 分母值，用于判断小样本
 * @returns {{ current: number|null, previous: number|null, delta: number|null, deltaPercent: number|null, unit: string, direction: string, isRate: boolean, smallSample: boolean, improved: boolean|null }|null}
 */
export function getMoM(code, trend, months, denominator) {
  const series = trend?.[code];
  if (!series || !Array.isArray(series) || series.length < 2) return null;

  const current = series[series.length - 1];
  const previous = series[series.length - 2];

  if (current == null || previous == null || Number.isNaN(current) || Number.isNaN(previous)) {
    return null;
  }

  const direction = getDirection(code);
  const isRate = isRateType(code);
  const unit = getUnit(code);
  const smallSample = denominator != null && denominator < 30;

  const delta = current - previous;
  const deltaPercent = previous !== 0 ? (delta / Math.abs(previous)) * 100 : null;

  // 方向感知：判断是否改善
  let improved = null;
  if (direction === 'higher_better') {
    improved = delta > 0;
  } else if (direction === 'lower_better') {
    improved = delta < 0;
  }

  return {
    current,
    previous,
    delta,
    deltaPercent,
    unit,
    direction,
    isRate,
    smallSample,
    improved,
  };
}

/**
 * 同比：本期 vs 去年同期
 * @param {string} code 指标码
 * @param {Object} trend { code: [月度值...] }
 * @param {string[]} months ['2026-01', '2026-02', ...]
 * @param {Object} [yoyTrend] 去年同期的 trend 数据（如无则返回 null）
 * @param {string[]} [yoyMonths] 去年同期的 months
 * @param {number} [denominator] 分母值
 * @returns {{ current: number|null, yoy: number|null, delta: number|null, deltaPercent: number|null, unit: string, direction: string, isRate: boolean, smallSample: boolean, improved: boolean|null }|null}
 */
export function getYoY(code, trend, months, yoyTrend, yoyMonths, denominator) {
  const series = trend?.[code];
  if (!series || !Array.isArray(series) || series.length < 1) return null;

  const current = series[series.length - 1];
  if (current == null || Number.isNaN(current)) return null;

  // 没有去年同期数据
  if (!yoyTrend || !yoyMonths) return null;

  const yoySeries = yoyTrend[code];
  if (!yoySeries || !Array.isArray(yoySeries) || yoySeries.length < 1) return null;

  const yoy = yoySeries[yoySeries.length - 1];
  if (yoy == null || Number.isNaN(yoy)) return null;

  const direction = getDirection(code);
  const isRate = isRateType(code);
  const unit = getUnit(code);
  const smallSample = denominator != null && denominator < 30;

  const delta = current - yoy;
  const deltaPercent = yoy !== 0 ? (delta / Math.abs(yoy)) * 100 : null;

  let improved = null;
  if (direction === 'higher_better') {
    improved = delta > 0;
  } else if (direction === 'lower_better') {
    improved = delta < 0;
  }

  return {
    current,
    yoy,
    delta,
    deltaPercent,
    unit,
    direction,
    isRate,
    smallSample,
    improved,
  };
}

/**
 * 格式化差值显示文本
 * @param {Object} result getMoM 或 getYoY 的返回值
 * @param {'mom'|'yoy'} type 环比或同比
 * @returns {{ text: string, tooltip: string, cssClass: string, arrow: string }}
 */
export function formatDelta(result, type = 'mom') {
  if (!result || result.delta == null) {
    return { text: '—', tooltip: '暂无数据', cssClass: 'faint', arrow: '' };
  }

  const { delta, deltaPercent, isRate, unit, improved, smallSample } = result;
  const label = type === 'mom' ? '环比' : '同比';

  let text = '';
  let tooltip = '';

  if (isRate) {
    // 率类：用百分点 pp
    const pp = Math.abs(delta).toFixed(1);
    const sign = delta > 0 ? '+' : delta < 0 ? '−' : '';
    text = `${sign}${pp}pp`;
    tooltip = `${label}变化：${sign}${pp}百分点（pp）`;
  } else {
    // 比值类：绝对差 + 变化率
    const absDelta = Math.abs(delta).toFixed(2);
    const sign = delta > 0 ? '+' : delta < 0 ? '−' : '';
    text = `${sign}${absDelta}`;
    if (deltaPercent != null) {
      text += ` (${deltaPercent > 0 ? '+' : ''}${deltaPercent.toFixed(1)}%)`;
    }
    tooltip = `${label}变化：${sign}${absDelta}`;
    if (deltaPercent != null) {
      tooltip += `，变化率 ${deltaPercent > 0 ? '+' : ''}${deltaPercent.toFixed(1)}%`;
    }
  }

  if (smallSample) {
    tooltip += '；分母较小（<30），波动不代表趋势';
  }

  // 方向感知 CSS class
  let cssClass = 'faint';
  if (improved === true) cssClass = 'good';
  else if (improved === false) cssClass = 'bad';

  // 箭头
  let arrow = '';
  if (delta > 0) arrow = '↑';
  else if (delta < 0) arrow = '↓';
  else arrow = '→';

  return { text, tooltip, cssClass, arrow, smallSample };
}

/**
 * 格式化数值显示（统一精度规则）
 * @param {number|null} value
 * @param {string} code 指标码
 * @returns {string}
 */
export function formatValue(value, code) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  const isRate = isRateType(code);
  const ind = INDICATORS.find(i => i.code === code);
  if (ind?.type === 'proportion') return Number(value).toFixed(2);
  if (isRate) return Number(value).toFixed(1);
  return String(Math.round(Number(value)));
}
