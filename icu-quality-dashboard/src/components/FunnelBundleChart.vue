<template>
  <div ref="chartRef" class="funnel-chart" :style="{ height: height + 'px' }"></div>
</template>

<script setup>
/**
 * FunnelBundleChart — Sepsis Bundle 漏斗
 * ICU-05-1h → 3h → 6h，每层标注达成率与环节流失。
 */
import { ref, watch, onMounted, onUnmounted, shallowRef } from 'vue';
import * as echarts from 'echarts';
import { baseChartOption, deepMerge, SEMANTIC } from '../utils/chartTheme.js';

const props = defineProps({
  /** 数据项 [{ name, value, code }] */
  data: { type: Array, default: () => [] },
  /** 高度 */
  height: { type: Number, default: 280 },
});

const chartRef = ref(null);
const chartInstance = shallowRef(null);

const FUNNEL_COLORS = [SEMANTIC.brand, SEMANTIC.good, '#0891b2'];

function buildOption() {
  const base = baseChartOption();

  const funnelData = props.data.map((d, i) => ({
    name: d.name,
    value: d.value || 0,
    itemStyle: { color: FUNNEL_COLORS[i % FUNNEL_COLORS.length] },
  }));

  // 计算环节流失
  const lossLabels = [];
  for (let i = 1; i < props.data.length; i++) {
    const prev = props.data[i - 1]?.value || 0;
    const curr = props.data[i]?.value || 0;
    if (prev > 0) {
      const loss = ((prev - curr) / prev * 100).toFixed(1);
      lossLabels.push({ from: props.data[i - 1].name, to: props.data[i].name, loss: loss + '%' });
    }
  }

  const option = {
    tooltip: {
      trigger: 'item',
      formatter(p) {
        const idx = p.dataIndex;
        const item = props.data[idx];
        let html = `<div style="font-weight:600;margin-bottom:4px">${item.name}</div>`;
        html += `<div>达成率：<b>${item.value}%</b></div>`;
        if (idx > 0) {
          const prev = props.data[idx - 1]?.value || 0;
          const loss = prev > 0 ? ((prev - item.value) / prev * 100).toFixed(1) : '—';
          html += `<div>环节流失：${loss}%</div>`;
        }
        return html;
      },
    },
    series: [
      {
        type: 'funnel',
        left: '10%',
        top: 20,
        bottom: 20,
        width: '80%',
        min: 0,
        max: 100,
        minSize: '20%',
        maxSize: '100%',
        sort: 'descending',
        gap: 4,
        label: {
          show: true,
          position: 'inside',
          formatter(p) {
            const idx = p.dataIndex;
            let text = `${p.name}\n${p.value}%`;
            if (idx > 0) {
              const prev = props.data[idx - 1]?.value || 0;
              if (prev > 0) {
                const loss = ((prev - p.value) / prev * 100).toFixed(1);
                text += `\n↓ -${loss}%`;
              }
            }
            return text;
          },
          color: '#fff',
          fontSize: 12,
          fontWeight: 600,
          lineHeight: 18,
        },
        data: funnelData,
      },
    ],
  };

  return deepMerge(base, option);
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

watch(() => props.data, updateChart, { deep: true });
</script>

<style scoped>
.funnel-chart {
  width: 100%;
}
</style>
