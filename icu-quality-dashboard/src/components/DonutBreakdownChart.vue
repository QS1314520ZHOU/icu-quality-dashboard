<template>
  <div ref="chartRef" class="donut-chart" :style="{ height: height + 'px' }"></div>
</template>

<script setup>
/**
 * DonutBreakdownChart — 甜甜圈
 * 类别 ≤5，中心显示总数与标题，图例在右侧两列。
 * 仅用于占比之和为 100% 的构成分析。
 */
import { ref, watch, onMounted, onUnmounted, shallowRef } from 'vue';
import * as echarts from 'echarts';
import { baseChartOption, deepMerge, SERIES_COLORS, SEMANTIC } from '../utils/chartTheme.js';

const props = defineProps({
  /** 数据项 [{ name, value }] */
  data: { type: Array, default: () => [] },
  /** 中心标题 */
  title: { type: String, default: '' },
  /** 单位 */
  unit: { type: String, default: '' },
  /** 高度 */
  height: { type: Number, default: 280 },
});

const chartRef = ref(null);
const chartInstance = shallowRef(null);

function buildOption() {
  const base = baseChartOption();

  const total = props.data.reduce((sum, d) => sum + (d.value || 0), 0);

  const option = {
    tooltip: {
      trigger: 'item',
      formatter(p) {
        return `<div style="font-weight:600;margin-bottom:4px">${p.name}</div>
                <div>${p.value}${props.unit}</div>
                <div>占比 ${p.percent}%</div>`;
      },
    },
    legend: {
      orient: 'vertical',
      right: 10,
      top: 'center',
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: SEMANTIC.textSub, fontSize: 12 },
    },
    series: [
      {
        type: 'pie',
        radius: ['45%', '70%'],
        center: ['40%', '50%'],
        avoidLabelOverlap: false,
        label: {
          show: true,
          position: 'center',
          formatter: `{title|${props.title}}\n{total|${total}${props.unit}}`,
          rich: {
            title: { fontSize: 12, color: SEMANTIC.textSub, lineHeight: 20 },
            total: { fontSize: 20, fontWeight: 700, color: SEMANTIC.text, lineHeight: 30 },
          },
        },
        labelLine: { show: false },
        data: props.data.map((d, i) => ({
          name: d.name,
          value: d.value,
          itemStyle: { color: SERIES_COLORS[i % SERIES_COLORS.length] },
        })),
        emphasis: {
          itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.1)' },
        },
      },
    ],
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

watch(() => [props.data, props.title], updateChart, { deep: true });
</script>

<style scoped>
.donut-chart {
  width: 100%;
}
</style>
