<template>
  <div class="dashboard">
    <!-- 顶部：标题 + 筛选 -->
    <header class="db-header">
      <div class="db-title-row">
        <span class="db-dot"></span>
        <h1 class="db-title">ICU 重症医学专业医疗质量控制大屏</h1>
        <span class="db-badge">实时监控</span>
      </div>
      <div class="db-filters">
        <select v-model.number="year" @change="loadData">
          <option v-for="y in years" :key="y" :value="y">{{ y }}年</option>
        </select>
        <select v-model.number="startMonth" @change="loadData">
          <option v-for="m in 12" :key="m" :value="m">{{ m }}月</option>
        </select>
        <span class="db-sep">—</span>
        <select v-model.number="endMonth" @change="loadData">
          <option v-for="m in 12" :key="m" :value="m">{{ m }}月</option>
        </select>
        <select v-model="dept" @change="loadData">
          <option value="all">全部ICU</option>
          <option v-for="d in departments" :key="d.code" :value="d.code">{{ d.name }}</option>
        </select>
      </div>
    </header>

    <!-- KPI 指标卡片行 -->
    <section class="kpi-row">
      <div v-for="c in kpiList" :key="c.code" class="kpi-card" :class="c.status">
        <div class="kpi-icon">{{ iconFor(c.code) }}</div>
        <div class="kpi-body">
          <div class="kpi-name">{{ c.name }}</div>
          <div class="kpi-value">
            <span class="kpi-num">{{ c.value }}</span>
            <span class="kpi-unit">{{ c.unit }}</span>
          </div>
          <div class="kpi-status">{{ statusLabel(c.status) }}</div>
        </div>
      </div>
    </section>

    <!-- 主体：图表网格 -->
    <section class="main-grid">
      <!-- 左列：仪表盘 + 对标 -->
      <div class="grid-col col-left">
        <div class="panel">
          <h3 class="panel-title">关键比率指标</h3>
          <div class="gauge-grid">
            <GaugeChart v-for="g in gaugeList.slice(0, 6)" :key="g.code"
              :name="g.name" :value="g.value" :unit="g.unit" :status="g.status" />
          </div>
        </div>
        <div class="panel">
          <h3 class="panel-title">人力资源配置对标</h3>
          <BarTargetChart :items="ratioItems" />
        </div>
      </div>

      <!-- 中列：趋势 + 控制图 -->
      <div class="grid-col col-mid">
        <div class="panel">
          <h3 class="panel-title">感染性休克 Bundle 完成率</h3>
          <TrendChart :months="bundleMonths" :series="bundleSeries" />
        </div>
        <div class="panel">
          <h3 class="panel-title">感染发病率监测（SPC 控制图）</h3>
          <ControlChart name="VAP发病率" :data="trendData['ICU-16']"
            :months="months" :ucl="15" unit="‰" />
          <ControlChart name="CRBSI发病率" :data="trendData['ICU-17']"
            :months="months" :ucl="5" unit="‰" />
        </div>
        <div class="panel">
          <h3 class="panel-title">标化病死指数（基准 1.0）</h3>
          <SmrChart :current="smrCurrent" :history="smrHistory" :months="months" />
        </div>
      </div>

      <!-- 右列：更多仪表盘 + AI -->
      <div class="grid-col col-right">
        <div class="panel">
          <h3 class="panel-title">核心质量指标</h3>
          <div class="gauge-grid">
            <GaugeChart v-for="g in gaugeList.slice(6, 12)" :key="g.code"
              :name="g.name" :value="g.value" :unit="g.unit" :status="g.status" />
          </div>
        </div>
        <div class="panel ai-panel-wrap">
          <AiPanel :analysis="ai" />
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import { INDICATORS, evalStatus } from '../config/indicators.js';
import { fetchIndicators, fetchAiAnalysis, fetchDepartments } from '../api/index.js';
import GaugeChart from '../components/GaugeChart.vue';
import TrendChart from '../components/TrendChart.vue';
import ControlChart from '../components/ControlChart.vue';
import AiPanel from '../components/AiPanel.vue';
import BarTargetChart from '../components/BarTargetChart.vue';
import SmrChart from '../components/SmrChart.vue';

const year = ref(2026), startMonth = ref(6), endMonth = ref(6), dept = ref('all');
const years = [2024, 2025, 2026];
const departments = ref([]);
const values = ref({});
const trendData = ref({});
const months = ref([]);
const ai = ref({ summary: '', abnormal: [] });

const periodStart = computed(() => `${year.value}-${String(startMonth.value).padStart(2, '0')}`);
const periodEnd = computed(() => `${year.value}-${String(endMonth.value).padStart(2, '0')}`);

function iconFor(code) {
  const m = { 'ICU-01': '🛏️', 'ICU-04': '📋', 'ICU-06': '💊', 'ICU-11': '📊', 'ICU-16': '🫁', 'ICU-14': '🚑' };
  return m[code] || '📈';
}
function statusLabel(s) {
  return { good: '达标', warn: '预警', danger: '异常' }[s] || '';
}

function buildItem(code) {
  const ind = INDICATORS.find(i => i.code === code);
  const val = values.value[code];
  if (val == null || typeof val === 'object') return null;
  return { code, name: ind.name, value: val, unit: ind.unit, status: evalStatus(ind, val) };
}

const kpiList = computed(() =>
  ['ICU-01', 'ICU-04', 'ICU-06', 'ICU-11', 'ICU-16', 'ICU-14'].map(buildItem).filter(Boolean));

const gaugeList = computed(() =>
  INDICATORS.filter(i => i.chart === 'gauge').map(i => buildItem(i.code)).filter(Boolean));

const bundleMonths = computed(() => months.value);
const bundleSeries = computed(() => {
  const b = values.value['ICU-05'] || {};
  return [
    { name: '1h', data: months.value.map(() => b['1h'] || null) },
    { name: '3h', data: months.value.map(() => b['3h'] || null) },
    { name: '6h', data: months.value.map(() => b['6h'] || null) },
  ];
});

const ratioItems = computed(() => [
  { name: '医师床位比', value: values.value['ICU-02'] ?? 0, target: 0.8 },
  { name: '护士床位比', value: values.value['ICU-03'] ?? 0, target: 2.5 },
]);

const smrCurrent = computed(() => values.value['ICU-11'] ?? 1);
const smrHistory = computed(() => trendData.value['ICU-11'] ?? []);

async function loadData() {
  const start = `${periodStart.value}-01`;
  const end = `${periodEnd.value}-28`;
  try {
    const res = await fetchIndicators(start, end, dept.value);
    values.value = res.values || {};
    trendData.value = res.trend || {};
    months.value = res.months || [];
  } catch { /* keep previous */ }
  try {
    const items = INDICATORS.map(i => buildItem(i.code)).filter(Boolean);
    ai.value = await fetchAiAnalysis(items, periodStart.value);
  } catch { /* keep previous */ }
}

onMounted(async () => {
  try { departments.value = await fetchDepartments(); } catch { /* */ }
  await loadData();
});
</script>

<style scoped>
.dashboard { padding: 20px 28px; min-height: 100vh; background: #f4f6fa; }

/* ---- 顶部 ---- */
.db-header { margin-bottom: 20px; }
.db-title-row { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.db-dot { width: 12px; height: 12px; border-radius: 50%; background: #10b981;
  box-shadow: 0 0 12px rgba(16,185,129,0.5); flex-shrink: 0; }
.db-title { font-size: 24px; font-weight: 700; color: #1a2b3c; margin: 0; letter-spacing: 1px; }
.db-badge { background: rgba(16,185,129,0.1); color: #10b981; font-size: 12px; font-weight: 600;
  padding: 3px 12px; border-radius: 20px; border: 1px solid rgba(16,185,129,0.2); }
.db-filters { display: flex; align-items: center; gap: 10px; }
.db-filters select { background: #fff; color: #1a2b3c; border: 1px solid #e6ebf2;
  border-radius: 8px; padding: 7px 14px; font-size: 14px; cursor: pointer; }
.db-filters select:hover { border-color: #2c7be5; }
.db-sep { color: #9aa7b8; font-size: 13px; }

/* ---- KPI 卡片 ---- */
.kpi-row { display: grid; grid-template-columns: repeat(6, 1fr); gap: 14px; margin-bottom: 20px; }
.kpi-card { background: #fff; border-radius: 10px; padding: 16px 18px; display: flex;
  align-items: center; gap: 14px; box-shadow: 0 1px 3px rgba(16,30,54,0.04), 0 1px 3px rgba(16,30,54,0.06);
  border: 1px solid #eef2f7; transition: transform .2s; }
.kpi-card:hover { transform: translateY(-2px); }
.kpi-card.good { border-left: 4px solid #1aa179; }
.kpi-card.warn { border-left: 4px solid #e08a00; }
.kpi-card.danger { border-left: 4px solid #d64545; }
.kpi-icon { font-size: 28px; flex-shrink: 0; }
.kpi-body { flex: 1; min-width: 0; }
.kpi-name { font-size: 13px; color: #6b7c93; margin-bottom: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kpi-value { display: flex; align-items: baseline; gap: 2px; }
.kpi-num { font-size: 28px; font-weight: 700; color: #1a2b3c; }
.kpi-unit { font-size: 13px; color: #9aa7b8; }
.kpi-status { font-size: 11px; font-weight: 600; margin-top: 2px; }
.kpi-card.good .kpi-status { color: #1aa179; }
.kpi-card.warn .kpi-status { color: #e08a00; }
.kpi-card.danger .kpi-status { color: #d64545; }

/* ---- 三列布局 ---- */
.main-grid { display: grid; grid-template-columns: 1fr 1.1fr 0.9fr; gap: 16px; }
.panel { background: #fff; border: 1px solid #eef2f7; border-radius: 10px;
  padding: 16px 18px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(16,30,54,0.04); }
.panel:last-child { margin-bottom: 0; }
.panel-title { font-size: 14px; color: #2c7be5; margin: 0 0 14px; padding-left: 10px;
  border-left: 3px solid #2c7be5; font-weight: 600; }
.gauge-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.grid-col { display: flex; flex-direction: column; }
.ai-panel-wrap { flex: 1; }
</style>
