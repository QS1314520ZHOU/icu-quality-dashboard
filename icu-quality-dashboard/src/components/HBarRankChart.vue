<template>
  <div ref="chartRef" class="hbar-rank-chart" :style="{ height: height + 'px' }"></div>
</template>

<script setup>
/**
 * HBarRankChart — 横向条形排行
 * 按「距目标缺口」降序，条内右端显示数值，虚线 markLine 显示目标。
 * 达标 var(--good)、预警 var(--warn)、异常 var(--danger)。
 */
import { ref, watch, onMounted, onUnmounted, shallowRef } from 'vue';
import * as echarts from 'echarts';
import { baseChartOption, deepMerge, SEMANTIC } from '../utils/chartTheme.js';

const props = defineProps({
  /** 数据项 [{ name, value, target, status }] */
  items: { type: Array, default: () => [] },
  /** 单位 */
  unit: { type: String, default: '' },
  /** 高度 */
  height: { type: Number, default: 300 },
});

const chartRef = ref(null);
const chartInstance = shallowRef(null);

const STATUS_COLORS = {
  good: SEMANTIC.good,
  warn: SEMANTIC.warn,
  danger: SEMANTIC.danger,
  unknown: SEMANTIC.textFaint,
};

function buildOption() {
  const base = baseChartOption();

  // 按距目标缺口降序排列
  const sorted = [...props.items].sort((a, b) => {
    const gapA = Math.abs((a.value || 0) - (a.target || 0));
    const gapB = Math.abs((b.value || 0) - (b.target || 0));
    return gapB - gapA;
  });

  const names = sorted.map(i => i.name);
  const values = sorted.map(i => i.value);
  const colors = sorted.map(i => STATUS_COLORS[i.status] || SEMANTIC.textFaint);

  // 目标线数据
  const targetValues = sorted.map(i => i.target);
  const hasTarget = sorted.some(i => i.target != null);

  const seriesConfig = [
    {
      type: 'bar',
      data: values.map((v, idx) => ({
        value: v,
        itemStyle: {
          color: colors[idx],
          borderRadius: [0, 4, 4, 0],
        },
      })),
      barMaxWidth: 20,
      label: {
        show: true,
        position: 'right',
        formatter: p => p.value + (props.unit || ''),
        color: SEMANTIC.text,
        fontSize: 12,
        fontWeight: 600,
      },
    },
  ];

  // 目标虚线
  if (hasTarget) {
    seriesConfig.push({
      type: 'bar',
      data: targetValues.map(t => ({
        value: 0,
        markLine: t != null ? {
          symbol: 'none',
          lineStyle: { type: 'dashed', color: SEMANTIC.danger, width: 1.5 },
          label: {
            show: true,
            formatter: '目标 ' + t,
            position: 'end',
            color: SEMANTIC.danger,
            fontSize: 11,
          },
          data: [{ xAxis: t }],
        } : undefined,
      })),
      silent: true,
    });
  }

  const option = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter(params) {
        const idx = params[0].dataIndex;
        const item = sorted[idx];
        let html = `<div style="font-weight:600;margin-bottom:4px">${item.name}</div>`;
        html += `<div>当前值：<b>${item.value}${props.unit}</b></div>`;
        if (item.target != null) html += `<div>目标值：${item.target}${props.unit}</div>`;
        return html;
      },
    },
    grid: { left: 10, right: 60, top: 10, bottom: 10, containLabel: true },
    xAxis: {
      type: 'value',
      axisLabel: { color: SEMANTIC.textSub, fontSize: 12, formatter: v => v + (props.unit || '') },
      splitLine: { lineStyle: { color: '#eef2f7' } },
    },
    yAxis: {
      type: 'category',
      data: names,
      inverse: true,
      axisLabel: { color: SEMANTIC.textSub, fontSize: 12, width: 100, overflow: 'truncate' },
      axisTick: { show: false },
    },
    series: seriesConfig,
  };

  return deepMerge(base, option);
}

function initChart() {
  if (!chartRef.value) return;
  if (chartInstance.value) chartInstance.value.dispose();
  chartInstance.value = echarts.init(chartRef.value, null, { renderer: 'canvas' });
  chartInstance.value.setOption(buildOption());
}

function updateChart() {
  if (!chartInstance.value) return;
  chartInstance.value.setOption(buildOption(), { notMerge: true, lazyUpdate: true });
}

let resizeObserver = null;

onMounted(() => {
  initChart();
  resizeObserver = new ResizeObserver(() => chartInstance.value?.resize());
  if (chartRef.value) resizeObserver.observe(chartRef.value);
});

onUnmounted(() => {
  resizeObserver?.disconnect();
  chartInstance.value?.dispose();
  chartInstance.value = null;
});

watch(() => props.items, updateChart, { deep: true });
</script>

<style scoped>
.hbar-rank-chart {
  width: 100%;
}
</style>
