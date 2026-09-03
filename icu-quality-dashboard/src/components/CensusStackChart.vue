<template>
  <div class="census-stack-chart">
    <div class="chart-title">患者动态趋势</div>
    <div class="chart-body" v-if="trend && trend.length">
      <div class="bar-group" v-for="(item, idx) in trend" :key="item.period || idx">
        <div class="stack">
          <div class="carry-in" :style="{ height: scale(item.carry_in) + '%' }" :title="'原有: ' + item.carry_in"></div>
          <div class="new-admit" :style="{ height: scale(item.new_admit) + '%' }" :title="'新入: ' + item.new_admit"></div>
        </div>
        <div class="bar-label">{{ formatPeriod(item.period) }}</div>
      </div>
    </div>
    <div class="empty" v-else>暂无趋势数据</div>
    <div class="legend">
      <span class="leg-item"><span class="dot carry-in"></span>原有</span>
      <span class="leg-item"><span class="dot new-admit"></span>新入</span>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  trend: { type: Array, default: () => [] },
});

function maxTotal() {
  return Math.max(1, ...props.trend.map(t => t.carry_in + t.new_admit));
}

function scale(val) {
  return Math.round((val / maxTotal()) * 100);
}

function formatPeriod(p) {
  if (!p) return '';
  const parts = p.split('-');
  return parts[1] ? parts[1] + '月' : p;
}
</script>

<style scoped>
.census-stack-chart { background:transparent; }
.chart-title { font-size:var(--fs-label); color:var(--text-sub); font-weight:600; margin-bottom:12px; }
.chart-body { display:flex; align-items:flex-end; gap:8px; height:120px; padding:0 4px; }
.bar-group { flex:1; display:flex; flex-direction:column; align-items:center; gap:4px; }
.stack { display:flex; flex-direction:column; width:100%; max-width:36px; height:100px; gap:1px; }
.carry-in { background:var(--brand); border-radius:3px 3px 0 0; min-height:2px; transition:height .3s; }
.new-admit { background:var(--warn); border-radius:0 0 3px 3px; min-height:2px; transition:height .3s; }
.bar-label { font-size:var(--fs-caption); color:var(--text-sub); }
.legend { display:flex; gap:14px; margin-top:10px; justify-content:center; }
.leg-item { display:flex; align-items:center; gap:5px; font-size:var(--fs-caption); color:var(--text-sub); }
.dot { width:10px; height:10px; border-radius:2px; }
.dot.carry-in { background:var(--brand); }
.dot.new-admit { background:var(--warn); }
.empty { color:var(--text-faint); font-size:var(--fs-caption); text-align:center; padding:20px; }
</style>
