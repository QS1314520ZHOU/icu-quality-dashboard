<template>
  <div class="dashboard">
    <!-- 顶部：标题 + 筛选 -->
    <header class="db-header">
      <div class="db-title-row">
        <span class="db-dot"></span>
        <h1 class="db-title">ICU 重症医学专业医疗质量控制大屏</h1>
      </div>
      <div class="db-filters">
        <select v-model.number="year" @change="loadData">
          <option v-for="y in years" :key="y" :value="y">{{ y }}年</option>
        </select>
        <select v-model.number="sMonth" @change="loadData">
          <option v-for="m in 12" :key="m" :value="m">{{ m }}月</option>
        </select>
        <span class="db-sep">—</span>
        <select v-model.number="eMonth" @change="loadData">
          <option v-for="m in 12" :key="m" :value="m">{{ m }}月</option>
        </select>
        <select v-model="dept" @change="loadData">
          <option value="all">全部ICU</option>
          <option v-for="d in departments" :key="d.code" :value="d.code">{{ d.name }}</option>
        </select>
      </div>
    </header>

    <!-- KPI 卡片 -->
    <section class="kpi-row">
      <div v-for="c in kpiList" :key="c.code" class="kpi-card" :class="c.status">
        <span class="kpi-icon">{{ iconFor(c.code) }}</span>
        <div class="kpi-body">
          <div class="kpi-name">{{ c.name }}</div>
          <div class="kpi-value"><span class="kpi-num">{{ c.value }}</span><span class="kpi-unit">{{ c.unit }}</span></div>
        </div>
      </div>
    </section>

    <!-- 图表区 -->
    <section class="main-grid">
      <div class="panel">
        <h3 class="panel-title">关键比率指标</h3>
        <div class="gauge-grid">
          <GaugeChart v-for="g in gaugeList.slice(0,6)" :key="g.code"
            :name="g.name" :value="g.value" :unit="g.unit" :status="g.status" />
        </div>
      </div>
      <div class="panel">
        <h3 class="panel-title">感染性休克 Bundle 完成率</h3>
        <div class="bundle-row">
          <div class="bundle-item"><span class="b-label">1h</span><span class="b-val" :class="bundleStatus('ICU-05-1h')">{{ values['ICU-05-1h'] ?? '—' }}%</span></div>
          <div class="bundle-item"><span class="b-label">3h</span><span class="b-val" :class="bundleStatus('ICU-05-3h')">{{ values['ICU-05-3h'] ?? '—' }}%</span></div>
          <div class="bundle-item"><span class="b-label">6h</span><span class="b-val" :class="bundleStatus('ICU-05-6h')">{{ values['ICU-05-6h'] ?? '—' }}%</span></div>
        </div>
      </div>
      <div class="panel">
        <h3 class="panel-title">感染发病率监测（SPC）</h3>
        <ControlChart name="VAP" :data="trendData['ICU-16']" :months="months" :ucl="15" unit="‰" />
        <ControlChart name="CRBSI" :data="trendData['ICU-17']" :months="months" :ucl="5" unit="‰" />
      </div>
      <div class="panel">
        <h3 class="panel-title">人力资源配置对标</h3>
        <BarTargetChart :items="ratioItems" />
      </div>
      <div class="panel">
        <h3 class="panel-title">标化病死指数（基准 1.0）</h3>
        <SmrChart :current="smrCurrent" :history="smrHistory" :months="months" />
      </div>
      <div class="panel">
        <AiPanel :analysis="ai" />
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue';
import { INDICATORS, evalStatus } from '../config/indicators.js';
import { fetchIndicators, fetchAiAnalysis, fetchDepartments } from '../api/index.js';
import GaugeChart from '../components/GaugeChart.vue';
import TrendChart from '../components/TrendChart.vue';
import ControlChart from '../components/ControlChart.vue';
import AiPanel from '../components/AiPanel.vue';
import BarTargetChart from '../components/BarTargetChart.vue';
import SmrChart from '../components/SmrChart.vue';

const year = ref(2026), sMonth = ref(6), eMonth = ref(6), dept = ref('all');
const years = [2024, 2025, 2026];
const departments = ref([]);
const values = ref({}); const trendData = ref({}); const months = ref([]);
const ai = ref({ summary: '', abnormal: [] });

const ps = computed(() => `${year.value}-${String(sMonth.value).padStart(2,'0')}`);
const pe = computed(() => `${year.value}-${String(eMonth.value).padStart(2,'0')}`);

function iconFor(c) { const m={ 'ICU-01':'🛏️','ICU-04':'📋','ICU-06':'💊','ICU-11':'📊','ICU-16':'🫁','ICU-14':'🚑' }; return m[c]||'📈'; }

function buildItem(code) {
  const ind = INDICATORS.find(i => i.code === code);
  const v = values.value[code];
  if (v == null || typeof v === 'object') return null;
  return { code, name: ind.name, value: v, unit: ind.unit, status: evalStatus(ind, v) };
}

const kpiList = computed(() => ['ICU-01','ICU-04','ICU-06','ICU-11','ICU-16','ICU-14'].map(buildItem).filter(Boolean));
const gaugeList = computed(() => INDICATORS.filter(i=>i.chart==='gauge').map(i=>buildItem(i.code)).filter(Boolean));
function bundleStatus(code) {
  const v = values.value[code];
  if (v == null) return '';
  const ind = INDICATORS.find(i => i.code === code);
  if (!ind) return '';
  const s = evalStatus(ind, v);
  return s === 'good' ? 'good' : s === 'warn' ? 'warn' : 'danger';
}
const ratioItems = computed(() => [
  { name:'医师床位比', value:values.value['ICU-02']??0, target:0.8 },
  { name:'护士床位比', value:values.value['ICU-03']??0, target:2.5 },
]);
const smrCurrent = computed(() => values.value['ICU-11'] ?? 1);
const smrHistory = computed(() => trendData.value['ICU-11'] ?? []);

async function loadData() {
  try {
    const res = await fetchIndicators(`${ps.value}-01`, `${pe.value}-28`, dept.value);
    values.value = res.values || {}; trendData.value = res.trend || {}; months.value = res.months || [];
  } catch { /* */ }
  try {
    const items = INDICATORS.map(i => buildItem(i.code)).filter(Boolean);
    ai.value = await fetchAiAnalysis(items, ps.value);
  } catch { /* */ }
}

// 同步 URL 参数 ↔ 大屏筛选
function syncFromURL() {
  const p = new URLSearchParams(window.location.search);
  const dc = p.get('deptCode');
  if (dc) dept.value = dc;
  const y = p.get('year'); if (y) year.value = +y;
  const sm = p.get('sMonth'); if (sm) sMonth.value = +sm;
  const em = p.get('eMonth'); if (em) eMonth.value = +em;
}
function syncToURL() {
  const u = new URL(window.location);
  dept.value === 'all' ? u.searchParams.delete('deptCode') : u.searchParams.set('deptCode', dept.value);
  u.searchParams.set('year', year.value);
  u.searchParams.set('sMonth', sMonth.value);
  u.searchParams.set('eMonth', eMonth.value);
  window.history.replaceState({}, '', u);
}
watch([dept, year, sMonth, eMonth], syncToURL);

onMounted(async () => {
  syncFromURL();
  try { departments.value = await fetchDepartments(); } catch { /* */ }
  await loadData();
});
</script>

<style scoped>
.dashboard { padding: 16px 24px; min-height: 100vh; background: #f4f6fa; }

.db-header { margin-bottom: 14px; }
.db-title-row { display:flex; align-items:center; gap:8px; margin-bottom:10px; }
.db-dot { width:8px; height:8px; border-radius:50%; background:#10b981;
  box-shadow:0 0 8px rgba(16,185,129,0.4); flex-shrink:0; }
.db-title { font-size:18px; font-weight:700; color:#1a2b3c; margin:0; }
.db-filters { display:flex; align-items:center; gap:8px; }
.db-filters select { background:#fff; color:#1a2b3c; border:1px solid #e6ebf2;
  border-radius:6px; padding:5px 10px; font-size:13px; cursor:pointer; }
.db-sep { color:#9aa7b8; font-size:12px; }

.kpi-row { display:grid; grid-template-columns:repeat(6,1fr); gap:10px; margin-bottom:14px; }
.kpi-card { background:#fff; border-radius:8px; padding:12px 14px; display:flex;
  align-items:center; gap:10px; box-shadow:0 1px 3px rgba(16,30,54,0.04);
  border:1px solid #eef2f7; border-left:3px solid #e6ebf2; }
.kpi-card.good { border-left-color:#1aa179; }
.kpi-card.warn { border-left-color:#e08a00; }
.kpi-card.danger { border-left-color:#d64545; }
.kpi-icon { font-size:22px; flex-shrink:0; }
.kpi-name { font-size:12px; color:#6b7c93; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.kpi-value { display:flex; align-items:baseline; gap:2px; }
.kpi-num { font-size:22px; font-weight:700; color:#1a2b3c; }
.kpi-unit { font-size:12px; color:#9aa7b8; }

.main-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }
.panel { background:#fff; border:1px solid #eef2f7; border-radius:8px;
  padding:12px 14px; box-shadow:0 1px 3px rgba(16,30,54,0.04); }
.panel-title { font-size:13px; color:#2c7be5; margin:0 0 10px; padding-left:8px;
  border-left:3px solid #2c7be5; font-weight:600; }
.gauge-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:4px; }
.bundle-row { display:flex; gap:16px; justify-content:center; padding:16px 0; }
.bundle-item { text-align:center; }
.b-label { display:block; font-size:12px; color:#6b7c93; margin-bottom:4px; }
.b-val { font-size:26px; font-weight:700; }
.b-val.good { color:var(--good); }
.b-val.warn { color:var(--warn); }
.b-val.danger { color:var(--danger); }
</style>
