<template>
  <div class="ring-progress" :class="status">
    <div class="ring-wrap">
      <div ref="chartRef" class="ring-chart"></div>
      <div class="ring-center">
        <span class="ring-line">
          <span class="ring-num tabular-nums">{{ displayValue }}</span>
          <span v-if="unit && displayValue !== '—'" class="ring-unit">{{ unit }}</span>
        </span>
      </div>
    </div>
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
 * 中心数字用 HTML 叠加层渲染：数字 + 单位同行基线排版（2.5:1 / 67.1%），
 * echarts 只画环，不承担文字。
 */
import { computed, ref, watch, onMounted, onUnmounted, shallowRef } from 'vue';
import * as echarts from 'echarts';
import { SEMANTIC } from '../utils/chartTheme.js';

const props = defineProps({
  name: { type: String, default: '' },
  value: { type: Number, default: 0 },
  unit: { type: String, default: '' },
  status: { type: String, default: 'unknown' },
  numeratorLabel: { type: String, default: '' },
  numerator: { type: [Number, String], default: '' },
  denominatorLabel: { type: String, default: '' },
  denominator: { type: [Number, String], default: '' },
  max: { type: Number, default: 100 },
});

const chartRef = ref(null);
const chartInstance = shallowRef(null);

const displayValue = computed(() => {
  const v = props.value;
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  // 最多两位小数，去掉多余的 0（67.1 → 67.1，2.50 → 2.5，86 → 86）
  return String(Math.round(n * 100) / 100);
});

const STATUS_COLORS = {
  good: SEMANTIC.good,
  warn: SEMANTIC.warn,
  danger: SEMANTIC.danger,
  unknown: SEMANTIC.textFaint,
};

function buildOption() {
  const color = STATUS_COLORS[props.status] || SEMANTIC.textFaint;
  const val = Number(props.value) || 0;
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
        label: { show: false },
        labelLine: { show: false },
        data: [
          { value: pct, itemStyle: { color } },
          { value: Math.max(100 - pct, 0), itemStyle: { color: SEMANTIC.border } },
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
  gap: 8px;
}

.ring-wrap {
  position: relative;
  width: 100%;
}

.ring-chart {
  width: 100%;
  height: 104px;
}

/* 中心数字：HTML 叠加，数字与单位同行、基线对齐 */
.ring-center {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.ring-line {
  display: inline-flex;
  align-items: baseline;
  line-height: 1;
}
.ring-num {
  font-size: 21px;
  font-weight: 700;
  color: var(--text-title);
  letter-spacing: -0.01em;
}
.ring-unit {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-sub);
  margin-left: 1.5px;
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
  max-width: 220px;
}

.ring-detail {
  font-size: 11px;
  color: var(--text-faint);
  line-height: 1.4;
}
</style>
