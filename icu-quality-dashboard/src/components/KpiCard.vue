<template>
  <div class="kpi-card" :class="status">
    <div class="kpi-name">{{ name }}</div>
    <div class="kpi-value">{{ value }}<span class="unit">{{ unit }}</span></div>
    <div class="kpi-bar"><span :style="{ width: barWidth }"></span></div>
  </div>
</template>

<script setup>
import { computed } from 'vue';
const props = defineProps({ name: String, value: Number, unit: String, status: String });
const barWidth = computed(() => Math.min(props.value, 100) + '%');
</script>

<style scoped>
.kpi-card { background: #ffffff; border-radius: 8px; padding: 16px 20px;
  border-left: 4px solid #0052d9; box-shadow: 0 4px 12px rgba(0,0,0,0.03); border-top: 1px solid rgba(0,0,0,0.02);
  border-right: 1px solid rgba(0,0,0,0.02); border-bottom: 1px solid rgba(0,0,0,0.02); }
.kpi-card.good { border-left-color: #10b981; }
.kpi-card.warn { border-left-color: #f59e0b; }
.kpi-card.danger { border-left-color: #ef4444; }
.kpi-name { font-size: 13px; color: #64748b; margin-bottom: 8px; font-weight: 500; }
.kpi-value { font-size: 30px; font-weight: bold; color: #1e293b; display: flex; align-items: baseline; }
.unit { font-size: 14px; color: #64748b; margin-left: 4px; }
.kpi-bar { height: 4px; background: rgba(0,0,0,0.05); border-radius: 2px; margin-top: 10px; }
.kpi-bar span { display: block; height: 100%; border-radius: 2px;
  background: linear-gradient(90deg, #0052d9, #10b981); transition: width .6s; }
</style>
