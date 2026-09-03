<template>
  <div class="ring-progress" :class="status">
    <div ref="chartRef" class="ring-chart"></div>
    <div class="ring-meta">
      <span class="ring-name" :title="name">{{ name }}</span>
      <span v-if="numeratorLabel" class="ring-detail">
        {{ numeratorLabel }} {{ numerator }} / {{ denominatorLabel }} {{ denominator }}
      </span>
    </div>
  </div>
</template>

<script setup>
/**
 * RingProgress — 环形进度（结构指标用）
 * 中心大数值 + 单位，环下方两行灰字显示分子/分母名称与数值。
 */
import { ref, watch, onMounted, onUnmounted, shallowRef } from 'vue';
import * as echarts from 'echarts';
import { SEMANTIC } from '../utils/chartTheme.js';

const props = defineProps({
  /** 指标名称 */
  name: { type: String, default: '' },
  /** 当前值 */
  value: { type: Number, default: 0 },
  /** 单位 */
  unit: { type: String, default: '' },
  /** 状态 */
  status: { type: String, default: 'unknown' },
  /** 分子标签 */
  numeratorLabel: { type: String, default: '' },
  /** 分子值 */
  numerator: { type: [Number, String], default: '' },
  /** 分母标签 */
  denominatorLabel: { type: String, default: '' },
  /** 分母值 */
  denominator: { type: [Number, String], default: '' },
  /** 最大值（默认 100） */
  max: { type: Number, default: 100 },
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
  const color = STATUS_COLORS[props.status] || SEMANTIC.textFaint;
  const val = props.value || 0;
  const pct = props.max > 0 ? (val / props.max * 100) : 0;

  return {
    animation: false,
    series: [
      {
        type: 'pie',
        radius: ['65%', '85%'],
        center: ['50%', '50%'],
        startAngle: 90,
        avoidLabelOverlap: false,
        label: {
          show: true,
          position: 'center',
          formatter: `{value|${val}}\n{unit|${props.unit}}`,
          rich: {
            value: { fontSize: 22, fontWeight: 700, color: SEMANTIC.text, lineHeight: 28 },
            unit: { fontSize: 12, color: SEMANTIC.textSub, lineHeight: 18 },
          },
        },
        data: [
          { value: pct, itemStyle: { color } },
          { value: 100 - pct, itemStyle: { color: SEMANTIC.border } },
        ],
        silent: true,
      },
    ],
  };
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

watch(() => [props.value, props.status, props.max], updateChart);
</script>

<style scoped>
.ring-progress {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.ring-chart {
  width: 100%;
  height: 100px;
}

.ring-meta {
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ring-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-body);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 120px;
}

.ring-detail {
  font-size: 11px;
  color: var(--text-faint);
  line-height: 1.4;
}
</style>
