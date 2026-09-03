<template>
  <div ref="el" class="chart"></div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue';
import * as echarts from 'echarts';
import { baseChartOption, deepMerge, SEMANTIC } from '../utils/chartTheme.js';

const props = defineProps({
  current: Number,        // 当前SMR，如 0.92
  history: Array,         // 历史趋势 [0.95, 1.05, 0.98, ...]
  months: Array,
});
const el = ref(null);
let chart = null;

function colorOf(v) {
  if (typeof v !== 'number') return SEMANTIC.textFaint;
  if (v < 1) return SEMANTIC.good;      // 优于预期
  if (v <= 1.2) return SEMANTIC.warn;   // 略差
  return SEMANTIC.danger;               // 明显差于预期
}

function render() {
  if (!chart) return;
  chart.setOption(deepMerge(baseChartOption(), {
    title: {
      text: `标化病死指数 SMR`, left: 'center', top: 0,
      textStyle: { color: SEMANTIC.textSub, fontSize: 13, fontWeight: 600 },
      subtext: props.current < 1 ? '优于预期' : (props.current <= 1.2 ? '接近预期' : '差于预期'),
      subtextStyle: { color: colorOf(props.current), fontSize: 12 },
    },
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 20, top: 64, bottom: 24 },
    xAxis: { type: 'category', data: props.months },
    yAxis: {
      type: 'value', min: 0.5, max: 1.5,
    },
    series: [{
      type: 'line', data: props.history, smooth: true,
      lineStyle: { color: SEMANTIC.brand, width: 2 },
      itemStyle: {
        color: p => colorOf(p.data),  // 每个点按SMR染色
      },
      symbolSize: 8,
      markLine: {
        symbol: 'none',
        data: [{
          yAxis: 1.0, name: '基准线',
          lineStyle: { color: SEMANTIC.danger, width: 2 },
          label: { formatter: '基准 1.0', color: SEMANTIC.danger, position: 'end' },
        }],
      },
      markArea: {
        silent: true,
        data: [
          [{ yAxis: 0.5, itemStyle: { color: 'rgba(14,122,82,0.06)' } }, { yAxis: 1.0 }],
          [{ yAxis: 1.0, itemStyle: { color: 'rgba(198,40,40,0.04)' } }, { yAxis: 1.5 }],
        ],
      },
    }],
  }));
}
onMounted(() => { chart = echarts.init(el.value); render(); });
watch(() => [props.current, props.history], render, { deep: true });
</script>

<style scoped>.chart { width: 100%; height: 220px; }</style>
