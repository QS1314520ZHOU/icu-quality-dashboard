<template>
  <div ref="chartRef" class="sparkline" :style="{ height: height + 'px' }"></div>
</template>

<script setup>
/**
 * Sparkline — 无坐标轴迷你折线
 * 高 28px，颜色 var(--brand)，最后一个点加实心圆点。
 * 数据取 trend[code] 最近 12 期。
 */
import { ref, watch, onMounted, onUnmounted, shallowRef } from 'vue';
import * as echarts from 'echarts';
import { SEMANTIC } from '../utils/chartTheme.js';

const props = defineProps({
  /** 趋势数据数组 */
  data: { type: Array, default: () => [] },
  /** 高度，默认 28 */
  height: { type: Number, default: 28 },
  /** 颜色，默认 brand */
  color: { type: String, default: '' },
});

const chartRef = ref(null);
const chartInstance = shallowRef(null);

function buildOption() {
  const seriesData = (props.data || []).slice(-12).filter(v => v != null && !Number.isNaN(v));
  if (seriesData.length === 0) {
    return { series: [] };
  }

  const lineColor = props.color || SEMANTIC.brand;

  return {
    animation: false,
    grid: { left: 0, right: 0, top: 2, bottom: 0, containLabel: false },
    xAxis: { type: 'category', show: false, data: seriesData.map((_, i) => i) },
    yAxis: { type: 'value', show: false, min: 'dataMin', max: 'dataMax' },
    series: [
      {
        type: 'line',
        data: seriesData,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 1.5, color: lineColor },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: lineColor + '30' },
            { offset: 1, color: lineColor + '05' },
          ]),
        },
        // 最后一个点加实心圆点
        markPoint: seriesData.length > 0 ? {
          symbol: 'circle',
          symbolSize: 5,
          itemStyle: { color: lineColor, borderColor: '#fff', borderWidth: 1 },
          data: [{ coord: [seriesData.length - 1, seriesData[seriesData.length - 1]] }],
          label: { show: false },
          animation: false,
        } : undefined,
      },
    ],
  };
}

function initChart() {
  if (!chartRef.value) return;
  if (chartInstance.value) {
    chartInstance.value.dispose();
  }
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
  resizeObserver = new ResizeObserver(() => {
    chartInstance.value?.resize();
  });
  if (chartRef.value) resizeObserver.observe(chartRef.value);
});

onUnmounted(() => {
  resizeObserver?.disconnect();
  chartInstance.value?.dispose();
  chartInstance.value = null;
});

watch(() => props.data, updateChart, { deep: true });
watch(() => props.color, updateChart);
</script>

<style scoped>
.sparkline {
  width: 100%;
  min-width: 60px;
}
</style>
