<template>
  <div ref="el" class="chart"></div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue';
import * as echarts from 'echarts';

const props = defineProps({
  current: Number,        // 当前SMR，如 0.92
  history: Array,         // 历史趋势 [0.95, 1.05, 0.98, ...]
  months: Array,
});
const el = ref(null);
let chart = null;

function colorOf(v) {
  if (typeof v !== 'number') return '#9aa7b8';
  if (v < 1) return '#10b981';      // 优于预期
  if (v <= 1.2) return '#f59e0b';   // 略差
  return '#ef4444';                 // 明显差于预期
}

function render() {
  if (!chart) return;
  chart.setOption({
    title: {
      text: `标化病死指数 SMR`, left: 'center', top: 0,
      textStyle: { color: '#6b7c93', fontSize: 13, fontWeight: 600 },
      subtext: props.current < 1 ? '优于预期' : (props.current <= 1.2 ? '接近预期' : '差于预期'),
      subtextStyle: { color: colorOf(props.current), fontSize: 12 },
    },
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 20, top: 64, bottom: 24 },
    xAxis: {
      type: 'category', data: props.months,
      axisLine: { lineStyle: { color: '#dfe6ef' } },
      axisLabel: { color: '#6b7c93' },
    },
    yAxis: {
      type: 'value', min: 0.5, max: 1.5,
      splitLine: { lineStyle: { color: '#eef2f7' } },
      axisLabel: { color: '#6b7c93' },
    },
    series: [{
      type: 'line', data: props.history, smooth: true,
      lineStyle: { color: '#0052d9', width: 2 },
      itemStyle: {
        color: p => colorOf(p.data),  // 每个点按SMR染色
      },
      symbolSize: 8,
      markLine: {
        symbol: 'none',
        data: [{
          yAxis: 1.0, name: '基准线',
          lineStyle: { color: '#ef4444', width: 2 },
          label: { formatter: '基准 1.0', color: '#ef4444', position: 'end' },
        }],
      },
      markArea: {
        silent: true,
        data: [
          [{ yAxis: 0.5, itemStyle: { color: 'rgba(16,185,129,0.04)' } }, { yAxis: 1.0 }], // 优于预期区
          [{ yAxis: 1.0, itemStyle: { color: 'rgba(239,68,68,0.03)' } }, { yAxis: 1.5 }],  // 差于预期区
        ],
      },
    }],
  });
}
onMounted(() => { chart = echarts.init(el.value); render(); });
watch(() => [props.current, props.history], render, { deep: true });
</script>

<style scoped>.chart { width: 100%; height: 220px; }</style>
