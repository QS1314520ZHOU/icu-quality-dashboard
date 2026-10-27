<template>
  <div class="year-trend">
    <div class="yt-toolbar">
      <span class="yt-note">年度趋势（按年聚合分子/分母）</span>
      <select v-model.number="rangeYears" aria-label="年数">
        <option :value="3">近 3 年</option>
        <option :value="5">近 5 年</option>
        <option :value="8">近 8 年</option>
      </select>
      <button class="yt-btn" :disabled="loading" @click="load">
        {{ loading ? '加载中…' : '刷新' }}
      </button>
    </div>
    <div v-if="error" class="yt-state">{{ error }}</div>
    <div v-else-if="!hasData" class="yt-state">{{ loading ? '加载中…' : '暂无年度数据' }}</div>
    <div v-else ref="chartEl" class="yt-chart" :style="{ height: height + 'px' }"></div>
  </div>
</template>

<script setup>
/**
 * YearTrendChart — 年度折线/柱状趋势
 * 数据来源 /api/indicators/{code}/trend-yearly
 */
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue';
import * as echarts from 'echarts/core';
import { LineChart, BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { fetchYearlyTrend } from '../api/index.js';

echartUse();
function echartUse() {
  echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);
}

const props = defineProps({
  code: { type: String, required: true },
  unit: { type: String, default: '' },
  height: { type: Number, default: 260 },
  chartType: { type: String, default: 'line' }, // line | bar
  icuUnit: { type: String, default: 'all' },
});

const chartEl = ref(null);
let chart = null;
const loading = ref(false);
const error = ref('');
const rangeYears = ref(5);
const seriesData = ref([]);
const yearLabels = ref([]);

const hasData = computed(() => seriesData.value.some(v => v != null));

function render() {
  if (!chartEl.value) return;
  if (!chart) chart = echarts.init(chartEl.value);
  const isBar = props.chartType === 'bar';
  chart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 44, right: 16, top: 28, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = params[0];
        const v = p?.value;
        return `${p?.name}<br/>${props.code}: <b>${v == null ? '—' : v}${props.unit || ''}</b>`;
      },
    },
    xAxis: {
      type: 'category',
      data: yearLabels.value,
      axisLine: { lineStyle: { color: 'rgba(120,140,170,0.35)' } },
      axisLabel: { color: '#6b7a90', fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      scale: true,
      splitLine: { lineStyle: { color: 'rgba(120,140,170,0.12)' } },
      axisLabel: { color: '#6b7a90', fontSize: 11 },
    },
    series: [{
      type: isBar ? 'bar' : 'line',
      name: props.code,
      data: seriesData.value,
      smooth: true,
      symbolSize: 7,
      lineStyle: { width: 2.5, color: '#1e5eb8' },
      itemStyle: { color: '#1e5eb8' },
      areaStyle: isBar ? undefined : { color: 'rgba(30,94,184,0.10)' },
      barMaxWidth: 28,
    }],
  }, true);
  chart.resize();
}

async function load() {
  const end = new Date().getFullYear();
  const start = end - rangeYears.value + 1;
  loading.value = true;
  error.value = '';
  try {
    const res = await fetchYearlyTrend(props.code, start, end, props.icuUnit);
    yearLabels.value = res.years || [];
    seriesData.value = res.values || [];
    await nextTick();
    render();
  } catch (e) {
    error.value = e.message || '年度趋势加载失败';
  } finally {
    loading.value = false;
  }
}

function onResize() { chart?.resize(); }

watch(() => [props.code, props.chartType, props.icuUnit], () => {
  chart?.dispose();
  chart = null;
  load();
});
watch(rangeYears, () => load());

onMounted(() => {
  load();
  window.addEventListener('resize', onResize);
});
onUnmounted(() => {
  window.removeEventListener('resize', onResize);
  chart?.dispose();
  chart = null;
});
</script>

<style scoped>
.year-trend { width: 100%; }
.yt-toolbar {
  display: flex; align-items: center; gap: 10px; margin-bottom: 8px;
}
.yt-note { font-size: 12px; color: var(--text-sub); flex: 1; }
.yt-toolbar select {
  font-size: 12px; padding: 4px 6px;
  border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-surface); color: var(--text-body);
}
.yt-btn {
  font-size: 12px; padding: 4px 10px;
  border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-surface); color: var(--text-body); cursor: pointer;
}
.yt-btn:disabled { opacity: 0.5; cursor: default; }
.yt-chart { width: 100%; }
.yt-state {
  padding: 32px; text-align: center;
  font-size: 13px; color: var(--text-sub);
  background: var(--bg-subtle, var(--bg-app));
  border-radius: 8px;
}
</style>
