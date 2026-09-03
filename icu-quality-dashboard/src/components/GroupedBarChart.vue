<template>
  <div ref="chartRef" class="grouped-bar-chart" :style="{ height: height + 'px' }"></div>
</template>

<script setup>
/**
 * GroupedBarChart — 分组柱状图
 * 用于「本期 / 上期 / 去年同期」对比和感染三项对比。
 * props: categories, series:[{name,data,color}], unit, targetLine?
 */
import { ref, watch, onMounted, onUnmounted, shallowRef } from 'vue';
import * as echarts from 'echarts';
import { baseChartOption, deepMerge, SEMANTIC } from '../utils/chartTheme.js';

const props = defineProps({
  /** x 轴类目 */
  categories: { type: Array, default: () => [] },
  /** 系列数据 [{ name, data, color }] */
  series: { type: Array, default: () => [] },
  /** 单位 */
  unit: { type: String, default: '' },
  /** 目标线值 */
  targetLine: { type: Number, default: null },
  /** 高度 */
  height: { type: Number, default: 300 },
  /** 是否水平 */
  horizontal: { type: Boolean, default: false },
});

const chartRef = ref(null);
const chartInstance = shallowRef(null);

function buildOption() {
  const base = baseChartOption();

  const seriesConfig = props.series.map((s, i) => ({
    name: s.name,
    type: 'bar',
    data: s.data,
    itemStyle: { color: s.color, borderRadius: [3, 3, 0, 0] },
    barGap: '10%',
    barMaxWidth: 28,
    emphasis: { itemStyle: { shadowBlur: 6, shadowColor: 'rgba(0,0,0,0.1)' } },
  }));

  // 添加目标线
  if (props.targetLine != null) {
    seriesConfig.push({
      name: '目标',
      type: 'line',
      data: props.categories.map(() => props.targetLine),
      lineStyle: { type: 'dashed', color: SEMANTIC.danger, width: 1.5 },
      symbol: 'none',
      silent: true,
      z: 10,
    });
  }

  const option = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter(params) {
        let html = `<div style="font-weight:600;margin-bottom:4px">${params[0].axisValue}</div>`;
        params.forEach(p => {
          if (p.seriesType === 'line') return;
          const val = p.value != null ? p.value : '—';
          html += `<div style="display:flex;align-items:center;gap:6px;margin:2px 0">
            <span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${p.color}"></span>
            <span>${p.seriesName}</span>
            <span style="font-weight:600;margin-left:auto">${val}${props.unit}</span>
          </div>`;
        });
        return html;
      },
    },
    legend: {
      show: props.series.length > 1,
      top: 0,
      right: 0,
    },
    grid: { left: 10, right: 20, top: 30, bottom: 10, containLabel: true },
    xAxis: {
      type: 'category',
      data: props.categories,
      axisLabel: { color: SEMANTIC.textSub, fontSize: 12, rotate: props.categories.length > 6 ? 30 : 0 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: SEMANTIC.textSub, fontSize: 12, formatter: v => v + (props.unit || '') },
      splitLine: { lineStyle: { color: '#eef2f7' } },
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

watch(() => [props.categories, props.series, props.targetLine], updateChart, { deep: true });
</script>

<style scoped>
.grouped-bar-chart {
  width: 100%;
}
</style>
