<!-- src/components/GaugeChart.vue -->
<template>
  <div ref="chartRef" class="gauge-box"></div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue';
import * as echarts from 'echarts';

const props = defineProps({
  name: String, value: Number, unit: String,
  status: String, // good/warn/danger
});

const chartRef = ref(null);
let chart = null;

const COLOR = { good: '#10b981', warn: '#f59e0b', danger: '#ef4444' };

function render() {
  if (!chart) return;
  chart.setOption({
    series: [{
      type: 'gauge', radius: '90%',
      startAngle: 210, endAngle: -30,
      min: 0, max: props.unit === '‰' ? 30 : (props.unit === '' ? 2 : 100),
      progress: { show: true, width: 12, itemStyle: { color: COLOR[props.status] } },
      axisLine: { lineStyle: { width: 12, color: [[1, '#eef2f7']] } },
      axisTick: { show: false },
      splitLine: { length: 8, lineStyle: { color: '#dfe6ef' } },
      axisLabel: { color: '#9aa7b8', fontSize: 9, distance: 14 },
      pointer: { width: 4, itemStyle: { color: COLOR[props.status] } },
      detail: {
        valueAnimation: true, fontSize: 26, fontWeight: 'bold',
        color: COLOR[props.status], offsetCenter: [0, '40%'],
        formatter: v => `${v}${props.unit}`,
      },
      title: { offsetCenter: [0, '75%'], color: '#6b7c93', fontSize: 12 },
      data: [{ value: props.value, name: props.name }],
    }],
  });
}

onMounted(() => { chart = echarts.init(chartRef.value); render(); });
watch(() => [props.value, props.status], render);
</script>

<style scoped>
.gauge-box { width: 100%; height: 200px; }
</style>
