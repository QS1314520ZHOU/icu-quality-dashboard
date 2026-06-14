<template>
  <div ref="el" class="chart"></div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue';
import * as echarts from 'echarts';

const props = defineProps({ months: Array, series: Array });
const el = ref(null);
let chart = null;
const COLORS = ['#10b981', '#0052d9', '#f59e0b'];

function render() {
  if (!chart) return;
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: props.series.map(s => s.name), textStyle: { color: '#6b7c93' }, top: 0 },
    grid: { left: 40, right: 20, top: 30, bottom: 24 },
    xAxis: { type: 'category', data: props.months,
      axisLine: { lineStyle: { color: '#dfe6ef' } },
      axisLabel: { color: '#6b7c93' } },
    yAxis: { type: 'value', max: 100, splitLine: { lineStyle: { color: '#eef2f7' } },
      axisLabel: { color: '#6b7c93' } },
    series: props.series.map((s, i) => ({
      name: s.name, type: 'line', smooth: true, data: s.data,
      lineStyle: { color: COLORS[i], width: 2 },
      itemStyle: { color: COLORS[i] },
      areaStyle: i === 0 ? { color: 'rgba(16,185,129,0.06)' } : undefined,
    })),
  });
}
onMounted(() => { chart = echarts.init(el.value); render(); });
watch(() => [props.months, props.series], render, { deep: true });
</script>

<style scoped>.chart { width: 100%; height: 200px; }</style>
