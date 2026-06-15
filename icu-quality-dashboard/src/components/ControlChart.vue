<template>
  <div ref="el" class="chart"></div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue';
import * as echarts from 'echarts';

const props = defineProps({
  name: String, data: Array, months: Array,
  ucl: Number, unit: String, // ucl = 控制上限(警戒线)
});
const el = ref(null);
let chart = null;

function render() {
  if (!chart || !props.data) return;
  const valid = props.data.filter(v => typeof v === 'number');
  const mean = valid.length ? valid.reduce((a, b) => a + b, 0) / valid.length : 0;
  chart.setOption({
    title: { text: props.name, left: 0, top: 0, textStyle: { color: '#6b7c93', fontSize: 13, fontWeight: 600 } },
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 20, top: 34, bottom: 24 },
    xAxis: { type: 'category', data: props.months,
      axisLine: { lineStyle: { color: '#dfe6ef' } },
      axisLabel: { color: '#6b7c93' } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#eef2f7' } },
      axisLabel: { color: '#6b7c93', formatter: `{value}${props.unit}` } },
    series: [{
      type: 'line', data: props.data, smooth: false,
      lineStyle: { color: '#0052d9', width: 2 }, itemStyle: { color: '#0052d9' },
      markLine: {
        symbol: 'none',
        data: [
          { yAxis: props.ucl, name: '警戒线(UCL)',
            lineStyle: { color: '#ef4444', type: 'dashed' },
            label: { color: '#ef4444', formatter: 'UCL' } },
          ...(valid.length ? [{ yAxis: +mean.toFixed(1), name: '均值',
            lineStyle: { color: '#10b981', type: 'dotted' },
            label: { color: '#10b981', formatter: '均值' } }] : []),
        ],
      },
      markPoint: {
        data: props.data.map((v, i) => typeof v === 'number' && v > props.ucl
          ? { coord: [i, v], itemStyle: { color: '#ef4444' } } : null).filter(Boolean),
      },
    }],
  });
}
onMounted(() => { chart = echarts.init(el.value); render(); });
watch(() => [props.data, props.ucl], render, { deep: true });
</script>

<style scoped>.chart { width: 100%; height: 180px; margin-top: 8px; }</style>
