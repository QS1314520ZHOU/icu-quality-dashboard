<template>
  <div ref="chartRef" class="radar-chart" :style="{ height: height + 'px' }"></div>
</template>

<script setup>
/**
 * RadarAssessChart — 评估类雷达
 * ICU-09 镇痛 / ICU-10 镇静 / ICU-18 意识（可扩展）
 * 叠加「目标值」第二圈作对照。
 */
import { ref, watch, onMounted, onUnmounted, shallowRef } from 'vue';
import * as echarts from 'echarts';
import { baseChartOption, deepMerge, SEMANTIC } from '../utils/chartTheme.js';

const props = defineProps({
  /** 数据项 [{ name, value, target, code }] */
  data: { type: Array, default: () => [] },
  /** 高度 */
  height: { type: Number, default: 280 },
});

const chartRef = ref(null);
const chartInstance = shallowRef(null);

function buildOption() {
  const base = baseChartOption();

  const indicators = props.data.map(d => ({
    name: d.name,
    max: 100,
  }));

  const currentValues = props.data.map(d => d.value || 0);
  const targetValues = props.data.map(d => d.target || 90);

  const option = {
    tooltip: {
      trigger: 'item',
      formatter(params) {
        if (params.componentType !== 'series') return '';
        const idx = params.dataIndex || 0;
        let html = '';
        if (Array.isArray(params.value)) {
          props.data.forEach((d, i) => {
            html += `<div style="font-weight:600;margin-bottom:2px">${d.name}</div>`;
            html += `<div>当前：${d.value}% ｜ 目标：${d.target}%</div>`;
          });
        }
        return html;
      },
    },
    legend: {
      data: ['当前值', '目标值'],
      bottom: 0,
      textStyle: { color: SEMANTIC.textSub, fontSize: 12 },
    },
    radar: {
      indicator: indicators,
      center: ['50%', '46%'],
      radius: '60%',
      axisName: {
        color: SEMANTIC.textSub,
        fontSize: 12,
      },
      splitArea: {
        areaStyle: {
          color: [SEMANTIC['brand-weak'], '#fff', SEMANTIC['brand-weak'], '#fff'],
        },
      },
      splitLine: { lineStyle: { color: SEMANTIC.border } },
      axisLine: { lineStyle: { color: SEMANTIC.border } },
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            name: '当前值',
            value: currentValues,
            symbol: 'circle',
            symbolSize: 6,
            lineStyle: { color: SEMANTIC.brand, width: 2 },
            itemStyle: { color: SEMANTIC.brand },
            areaStyle: { color: SEMANTIC.brand + '20' },
          },
          {
            name: '目标值',
            value: targetValues,
            symbol: 'diamond',
            symbolSize: 6,
            lineStyle: { color: SEMANTIC.danger, type: 'dashed', width: 1.5 },
            itemStyle: { color: SEMANTIC.danger },
            areaStyle: { color: 'transparent' },
          },
        ],
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

watch(() => props.data, updateChart, { deep: true });
</script>

<style scoped>
.radar-chart {
  width: 100%;
}
</style>
