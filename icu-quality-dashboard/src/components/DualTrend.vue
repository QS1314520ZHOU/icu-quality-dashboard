<template>
  <div class="dual-trend">
    <header class="dt-head">
      <div class="dt-title">
        <strong>{{ name }}</strong>
        <span v-if="codeLabel" class="dt-code">{{ codeLabel }}</span>
        <span class="dt-tag" :class="kindClass">{{ kindLabel }}</span>
        <span v-if="passLabel" class="dt-status" :class="passClass">{{ passLabel }}</span>
      </div>
      <div class="dt-target">目标：{{ targetText }}</div>
    </header>

    <div class="dt-grid">
      <section class="dt-panel">
        <div class="dt-panel-title"><i class="sq yearly"></i>年度趋势（按年汇总）</div>
        <div v-if="yearlyError" class="dt-msg">{{ yearlyError }}</div>
        <div v-else ref="yearlyEl" class="dt-chart"></div>
      </section>
      <section class="dt-panel">
        <div class="dt-panel-title"><i class="sq monthly"></i>月度趋势（{{ year }}年各月明细）</div>
        <div v-if="!hasMonthly" class="dt-msg">本年暂无月度数据</div>
        <div v-else ref="monthlyEl" class="dt-chart"></div>
      </section>
    </div>
    <p class="dt-foot">
      虚线为目标参考：≥目标取目标带下限，≤目标取上限，区间型显示上下限。年度值 = 该年分子合计÷分母合计；月度值为各月预聚合比值。
    </p>
  </div>
</template>

<script setup>
/**
 * DualTrend — 文章同款「年度趋势 + 月度趋势」并排双图，含目标参考线。
 */
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue';
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, MarkLineComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { INDICATORS } from '../config/indicators.js';
import { fetchYearlyTrend } from '../api/index.js';

echarts.use([LineChart, GridComponent, TooltipComponent, MarkLineComponent, CanvasRenderer]);

const props = defineProps({
  code: { type: String, required: true },
  name: { type: String, default: '' },
  /** 月度数据 { months: ['1月',...], values: [...] } 或数组对 */
  monthly: { type: Object, default: null },
  year: { type: Number, default: new Date().getFullYear() },
  icuUnit: { type: String, default: 'all' },
  status: { type: String, default: '' }, // good/warn/danger/'' 可选达标徽标
  kind: { type: String, default: '' },   // structure/process/outcome
});

const yearlyEl = ref(null);
const monthlyEl = ref(null);
let yearlyChart = null;
let monthlyChart = null;

const yearlyValues = ref([]);
const yearlyLabels = ref([]);
const yearlyError = ref('');

const ind = computed(() => INDICATORS.find(i => i.code === props.code));
const unit = computed(() => ind.value?.unit || '%');
const codeLabel = computed(() => ind.value?.displayCode || props.code);

const kindLabel = computed(() => ({ structure: '结构指标', process: '过程指标', outcome: '结果指标' })[props.kind] || '');
const kindClass = computed(() => props.kind || '');
const passLabel = computed(() => (props.status === 'good' ? '达标' : props.status === 'warn' ? '预警' : props.status === 'danger' ? '未达标' : ''));
const passClass = computed(() => props.status || '');

/** 目标参考：higher→下限；lower→上限；range→上下限数组 */
const targetLineValues = computed(() => {
  const th = ind.value?.thresholds?.good;
  if (!Array.isArray(th) || th.length < 2) return [];
  const dir = ind.value?.direction;
  if (dir === 'higher_better') return [Number(th[0])];
  if (dir === 'lower_better') return [Number(th[1])];
  return [Number(th[0]), Number(th[1])]; // range
});

const targetText = computed(() => {
  const lines = targetLineValues.value;
  const dir = ind.value?.direction;
  if (!lines.length) return '—';
  const fmt = v => `${v}${unit.value || ''}`;
  if (dir === 'higher_better') return `${fmt(lines[0])} (≥)`;
  if (dir === 'lower_better') return `${fmt(lines[0])} (≤)`;
  return `${fmt(lines[0])} ~ ${fmt(lines[1])}`;
});

const hasMonthly = computed(() => Array.isArray(props.monthly?.values) && props.monthly.values.some(v => v != null));

function markLineOpt() {
  const vals = targetLineValues.value;
  if (!vals.length) return {};
  return {
    silent: true,
    symbol: 'none',
    lineStyle: { type: 'dashed', color: '#22a06b', width: 1.5 },
    label: {
      show: true,
      position: 'insideEndTop',
      formatter: p => `目标 ${p.value}${unit.value || ''}`,
      color: '#22a06b',
      fontSize: 10,
    },
    data: vals.map(v => ({ yAxis: v })),
  };
}

function baseOption(categories, data, color) {
  return {
    grid: { left: 44, right: 18, top: 30, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: v => (v == null ? '—' : `${v}${unit.value || ''}`),
    },
    xAxis: {
      type: 'category',
      data: categories,
      axisLine: { lineStyle: { color: 'rgba(120,140,170,0.35)' } },
      axisLabel: { color: '#6b7a90', fontSize: 11 },
      boundaryGap: false,
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: '#6b7a90', fontSize: 11, formatter: `{value}${unit.value || ''}` },
      splitLine: { lineStyle: { color: 'rgba(120,140,170,0.12)' } },
    },
    series: [{
      type: 'line',
      data,
      smooth: true,
      connectNulls: false,
      symbolSize: 6,
      lineStyle: { width: 2.5, color },
      itemStyle: { color },
      areaStyle: { color: `${color}1a` },
      markLine: markLineOpt(),
      label: {
        show: true,
        position: 'bottom',
        fontSize: 10,
        color: '#8fa3c0',
        formatter: p => (p.value == null ? '' : `${p.value}`),
      },
    }],
  };
}

function renderCharts() {
  if (yearlyEl.value) {
    if (!yearlyChart) yearlyChart = echarts.init(yearlyEl.value);
    yearlyChart.setOption(baseOption(yearlyLabels.value, yearlyValues.value, '#3b82f6'), true);
    yearlyChart.resize();
  }
  if (monthlyEl.value) {
    if (!monthlyChart) monthlyChart = echarts.init(monthlyEl.value);
    const m = props.monthly || {};
    monthlyChart.setOption(baseOption(m.months || [], m.values || [], '#f59e0b'), true);
    monthlyChart.resize();
  }
}

async function loadYearly() {
  yearlyError.value = '';
  const end = props.year;
  const start = end - 4; // 近5年，对齐文章示例
  try {
    const res = await fetchYearlyTrend(props.code, start, end, props.icuUnit);
    yearlyLabels.value = (res.years || []).map(y => `${y}年`);
    yearlyValues.value = res.values || [];
  } catch (e) {
    yearlyError.value = e.message || '年度趋势加载失败';
    yearlyLabels.value = [];
    yearlyValues.value = [];
  }
}

function onResize() {
  yearlyChart?.resize();
  monthlyChart?.resize();
}

watch(() => [props.code, props.icuUnit, props.year], async () => {
  yearlyChart?.dispose(); yearlyChart = null;
  monthlyChart?.dispose(); monthlyChart = null;
  await loadYearly();
  await nextTick();
  renderCharts();
}, { deep: true });

watch(() => props.monthly, async () => {
  await nextTick();
  renderCharts();
}, { deep: true });

onMounted(async () => {
  await loadYearly();
  await nextTick();
  renderCharts();
  window.addEventListener('resize', onResize);
});
onUnmounted(() => {
  window.removeEventListener('resize', onResize);
  yearlyChart?.dispose();
  monthlyChart?.dispose();
  yearlyChart = null;
  monthlyChart = null;
});
</script>

<style scoped>
.dual-trend { min-width: 640px; }
.dt-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; margin-bottom: 12px; flex-wrap: wrap;
}
.dt-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.dt-title strong { font-size: 15px; color: var(--text-title); }
.dt-code { font-size: 11px; color: var(--text-faint); font-weight: 600; }
.dt-tag {
  font-size: 11px; padding: 2px 8px; border-radius: 10px;
  background: rgba(44,123,229,0.10); color: #2c7be5;
}
.dt-tag.structure { background: rgba(100,116,139,0.12); color: #64748b; }
.dt-tag.outcome { background: rgba(224,123,0,0.12); color: #c26a00; }
.dt-status {
  font-size: 11px; padding: 2px 8px; border-radius: 10px;
  background: rgba(21,150,107,0.12); color: #15966b;
}
.dt-status.warn { background: rgba(201,122,22,0.12); color: #c97a16; }
.dt-status.danger { background: rgba(207,64,64,0.12); color: #cf4040; }
.dt-target {
  font-size: 12px; color: var(--text-sub);
  background: var(--bg-subtle, #f1f5f9);
  border: 1px solid var(--border);
  padding: 4px 10px; border-radius: 6px;
}
.dt-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.dt-panel {
  background: var(--bg-subtle, #f8fafc);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 10px 6px;
}
.dt-panel-title {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; font-weight: 600; color: var(--text-sub);
  margin-bottom: 6px; padding-left: 2px;
}
.sq { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
.sq.yearly { background: #3b82f6; }
.sq.monthly { background: #f59e0b; }
.dt-chart { width: 100%; height: 260px; }
.dt-msg {
  height: 260px; display: flex; align-items: center; justify-content: center;
  font-size: 13px; color: var(--text-faint);
}
.dt-foot {
  margin: 10px 0 0;
  font-size: 11px; color: var(--text-faint); line-height: 1.5;
}
@media (max-width: 760px) {
  .dt-grid { grid-template-columns: 1fr; }
  .dual-trend { min-width: 0; }
}
</style>
