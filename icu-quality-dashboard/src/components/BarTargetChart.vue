<template>
  <div ref="el" class="chart"></div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue';
import * as echarts from 'echarts';

const props = defineProps({
  // items: [{ name:'医师床位比', value:0.9, target:0.8 }, ...]
  items: Array,
});
const el = ref(null);
let chart = null;

function render() {
  if (!chart || !props.items) return;
  const names = props.items.map(i => i.name);
  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 90, right: 50, top: 20, bottom: 20 },
    xAxis: {
      type: 'value', splitLine: { lineStyle: { color: '#eef2f7' } },
      axisLabel: { color: '#6b7c93' },
    },
    yAxis: {
      type: 'category', data: names,
      axisLine: { lineStyle: { color: '#dfe6ef' } },
      axisLabel: { color: '#6b7c93', fontSize: 13 },
    },
    series: [{
      type: 'bar', barWidth: 18,
      data: props.items.map(i => ({
        value: i.value,
        itemStyle: {
          color: i.value >= i.target ? '#10b981' : '#f59e0b',
          borderRadius: [0, 4, 4, 0],
        },
      })),
      label: { show: true, position: 'right', color: '#6b7c93',
        formatter: p => p.value.toFixed(2) },
      markLine: {
        symbol: 'none',
        data: props.items.map((i, idx) => ({
          yAxis: idx, xAxis: i.target,
          lineStyle: { color: '#ef4444', type: 'dashed' },
          label: { formatter: `标准${i.target}`, color: '#ef4444', fontSize: 10 },
        })),
      },
    }],
  });
}
onMounted(() => { chart = echarts.init(el.value); render(); });
watch(() => props.items, render, { deep: true });
</script>

<style scoped>.chart { width: 100%; height: 160px; }</style>
