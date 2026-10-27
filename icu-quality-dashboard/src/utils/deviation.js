/**
 * deviation.js — 预警设计：偏离度分级 + SPC 特殊波动 + 关注清单
 *
 * 医疗质量不采用「红绿灯」达标制，改为：
 * 1. 偏离度：与目标带（good 区间）的距离 → steady / mild / moderate / significant
 * 2. SPC：与本指标近 N 月自身基线比（均值 ±2σ），标记特殊原因波动
 * 3. 关注清单：结果显著偏离 → 过程显著偏离 → SPC 信号，按优先级排序
 */

/** 与目标带的相对偏离：0 = 带内；>0 = 带外相对距离 */
export function bandDeviation(value, goodBand) {
  const v = Number(value);
  if (value == null || Number.isNaN(v) || !Array.isArray(goodBand) || goodBand.length < 2) return null;
  const [lo, hi] = goodBand.map(Number);
  if (Number.isNaN(lo) || Number.isNaN(hi)) return null;
  if (v >= lo && v <= hi) return 0;
  const span = Math.max(Math.abs(hi - lo), 1e-6);
  return v < lo ? (lo - v) / span : (v - hi) / span;
}

/** 偏离度 → 分级（阈值可按院内实际再调） */
export function deviationLevel(dev) {
  if (dev == null) return 'unknown';
  if (dev <= 0.001) return 'steady';
  if (dev < 0.25) return 'mild';
  if (dev < 0.5) return 'moderate';
  return 'significant';
}

export const DEVIATION_META = {
  steady:    { label: '平稳',   color: '#5b8def', rank: 0 }, // 中性蓝，非「绿灯」
  mild:      { label: '轻度偏离', color: '#d4a017', rank: 1 },
  moderate:  { label: '中度偏离', color: '#e07b00', rank: 2 },
  significant:{ label: '显著偏离', color: '#b5451b', rank: 3 },
  unknown:   { label: '数据不足', color: '#6b7a90', rank: -1 },
};

/**
 * SPC：近 N 月序列上是否出现特殊原因波动（|x − mean| > 2σ）
 * @returns {{ special: boolean, mean: number|null, sigma: number|null, z: number|null }}
 */
export function spcSignal(series, currentValue, { window = 12, minPoints = 6, k = 2 } = {}) {
  const pts = (series || [])
    .map(v => Number(v))
    .filter(v => !Number.isNaN(v));
  const cur = Number(currentValue);
  if (Number.isNaN(cur) || pts.length < minPoints) {
    return { special: false, mean: null, sigma: null, z: null, insufficient: true };
  }
  const recent = pts.slice(-window);
  const mean = recent.reduce((a, b) => a + b, 0) / recent.length;
  const variance = recent.reduce((a, b) => a + (b - mean) ** 2, 0) / recent.length;
  const sigma = Math.sqrt(variance);
  if (sigma < 1e-9) {
    return { special: Math.abs(cur - mean) > 1e-9 && Math.abs(cur - mean) > 0.01, mean, sigma: 0, z: null };
  }
  const z = (cur - mean) / sigma;
  return { special: Math.abs(z) > k, mean, sigma, z };
}

/**
 * 单指标综合评估：偏离分级 + SPC
 * @param {Object} row 指标行 { code, name, value, unit, kind }
 * @param {number[]} monthly 该指标月度序列（可空）
 * @param {number[]} goodBand [lo, hi]
 */
export function evaluateIndicator(row, monthly, goodBand) {
  const dev = bandDeviation(row?.value, goodBand);
  const level = deviationLevel(dev);
  const spc = spcSignal(monthly, row?.value);
  return {
    code: row?.code,
    name: row?.name,
    value: row?.value,
    unit: row?.unit || '',
    kind: row?.kind,
    numerator: row?.numerator ?? null,
    denominator: row?.denominator ?? null,
    deviation: dev,
    level,
    levelMeta: DEVIATION_META[level] || DEVIATION_META.unknown,
    spc,
    goodBand: Array.isArray(goodBand) ? goodBand : null,
  };
}

/**
 * 构建关注清单（替代「异常清单」的红绿灯语义）
 * 优先级：结果显著偏离 → 过程显著偏离 → 任意 SPC 信号
 * @param {Array} evaluations evaluateIndicator 的结果列表（须含 kind: structure|process|outcome）
 */
export function buildActionList(evaluations) {
  const list = [];
  for (const e of evaluations) {
    if (!e || e.kind === 'structure') continue; // 结构类默认不进关注清单（变化通常不大）
    const isOutcome = e.kind === 'outcome';
    if (e.level === 'significant' || e.level === 'moderate') {
      list.push({
        ...e,
        priority: isOutcome ? 1 : 2,
        reason: isOutcome
          ? `结果指标${e.levelMeta.label}`
          : `过程指标${e.levelMeta.label}`,
      });
    } else if (e.spc?.special) {
      list.push({
        ...e,
        priority: isOutcome ? 3 : 4,
        reason: '相对自身近月基线出现特殊波动（SPC）',
      });
    } else if (e.level === 'mild' && isOutcome) {
      list.push({
        ...e,
        priority: 5,
        reason: '结果指标轻度偏离，结合过程解读',
      });
    }
  }
  list.sort((a, b) => {
    if (a.priority !== b.priority) return a.priority - b.priority;
    return (b.deviation ?? 0) - (a.deviation ?? 0);
  });
  return list;
}
