/**
 * chartTheme.js — ECharts 浅色主题基础配置
 * 统一网格线、轴线、tooltip、legend 等默认值，各图表组件按需合并。
 */

/* 色盲友好系列色板 */
export const SERIES_COLORS = [
  '#1e5eb8', // brand
  '#0e9f6e', // good
  '#b26a00', // warn
  '#c62828', // danger
  '#4f46c5', // ai
  '#0891b2', // cyan
];

/* 语义色 */
export const SEMANTIC = {
  good: '#0e7a52',
  'good-weak': '#e8f6ef',
  warn: '#b26a00',
  'warn-weak': '#fdf3e3',
  danger: '#c62828',
  'danger-weak': '#fdecec',
  brand: '#1e5eb8',
  'brand-weak': '#eaf1fb',
  ai: '#4f46c5',
  'ai-weak': '#eeedfb',
  text: '#3d4a63',
  textSub: '#6b7a94',
  textFaint: '#8b98ae',
  border: '#e5eaf2',
  borderStrong: '#d8e0ec',
};

/**
 * 返回浅色图表基础 option（直接 merge 到 setOption 中）
 */
export function baseChartOption() {
  return {
    color: SERIES_COLORS,
    backgroundColor: 'transparent',
    textStyle: {
      fontFamily: "'Segoe UI','HarmonyOS Sans','PingFang SC','Microsoft YaHei',system-ui,sans-serif",
      color: SEMANTIC.textSub,
      fontSize: 12,
    },
    grid: {
      containLabel: false,
    },
    tooltip: {
      backgroundColor: '#ffffff',
      borderColor: SEMANTIC.border,
      borderWidth: 1,
      borderRadius: 8,
      padding: [10, 14],
      textStyle: {
        color: SEMANTIC.text,
        fontSize: 13,
      },
      extraCssText: 'box-shadow:0 1px 2px rgba(16,24,40,.04),0 8px 24px rgba(16,24,40,.06);',
    },
    legend: {
      textStyle: {
        color: SEMANTIC.textSub,
        fontSize: 12,
      },
    },
    xAxis: {
      axisLine: { lineStyle: { color: SEMANTIC.border } },
      axisTick: { lineStyle: { color: SEMANTIC.border } },
      axisLabel: { color: SEMANTIC.textSub, fontSize: 12 },
      splitLine: { lineStyle: { color: SEMANTIC.border } },
    },
    yAxis: {
      axisLine: { lineStyle: { color: SEMANTIC.border } },
      axisTick: { lineStyle: { color: SEMANTIC.border } },
      axisLabel: { color: SEMANTIC.textSub, fontSize: 12 },
      splitLine: { lineStyle: { color: '#eef2f7' } },
    },
  };
}

/**
 * 深度合并：target 的每个 key 会被 source 覆盖，但嵌套对象递归合并
 */
export function deepMerge(target, source) {
  const out = { ...target };
  for (const key of Object.keys(source)) {
    if (
      source[key] &&
      typeof source[key] === 'object' &&
      !Array.isArray(source[key]) &&
      target[key] &&
      typeof target[key] === 'object' &&
      !Array.isArray(target[key])
    ) {
      out[key] = deepMerge(target[key], source[key]);
    } else {
      out[key] = source[key];
    }
  }
  return out;
}
