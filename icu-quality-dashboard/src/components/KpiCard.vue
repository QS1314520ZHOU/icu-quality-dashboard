<template>
  <div class="kpi-card" :class="status">
    <div class="kpi-name">{{ name }}</div>
    <div class="kpi-value tabular-nums">{{ value }}<span class="unit">{{ unit }}</span></div>
    <div class="kpi-bar"><span :style="{ width: barWidth }"></span></div>
  </div>
</template>

<script setup>
import { computed } from 'vue';
const props = defineProps({ name: String, value: Number, unit: String, status: String });
const barWidth = computed(() => Math.min(props.value, 100) + '%');
</script>

<style scoped>
.kpi-card {
  background: var(--bg-surface); border-radius: var(--radius-sm); padding: 16px 20px;
  border-left: 4px solid var(--brand); box-shadow: var(--shadow-card);
  border: 1px solid var(--border); border-left: 4px solid var(--brand);
}
.kpi-card.good { border-left-color: var(--good); }
.kpi-card.warn { border-left-color: var(--warn); }
.kpi-card.danger { border-left-color: var(--danger); }
.kpi-name { font-size: var(--fs-label); color: var(--text-sub); margin-bottom: 8px; font-weight: 500; }
.kpi-value { font-size: var(--fs-metric); font-weight: 700; color: var(--text-title); display: flex; align-items: baseline; }
.unit { font-size: var(--fs-body); color: var(--text-sub); margin-left: 4px; }
.kpi-bar { height: 4px; background: var(--bg-subtle); border-radius: 2px; margin-top: 10px; }
.kpi-bar span { display: block; height: 100%; border-radius: 2px;
  background: var(--brand); transition: width .6s; }
</style>
