<template>
  <div class="dashboard">
    <header class="db-header">
      <div>
        <div class="eyebrow">ICU 质控指挥舱</div>
        <h1>实时大屏看板</h1>
        <div class="meta">统计范围 {{ ps }} 至 {{ pe }}<span v-if="updatedAt"> · 更新 {{ updatedAt }}</span></div>
      </div>
      <div class="filters">
        <select v-model.number="year" @change="loadData">
          <option v-for="y in years" :key="y" :value="y">{{ y }}年</option>
        </select>
        <select v-model.number="sMonth" @change="loadData">
          <option v-for="m in 12" :key="m" :value="m">{{ m }}月</option>
        </select>
        <span>至</span>
        <select v-model.number="eMonth" @change="loadData">
          <option v-for="m in 12" :key="m" :value="m">{{ m }}月</option>
        </select>
        <select v-model="dept" @change="loadData">
          <option value="all">全部ICU</option>
          <option v-for="d in departments" :key="d.code" :value="d.code">{{ d.name }}</option>
        </select>
        <button class="secondary" @click="guideVisible=true">指标说明</button>
        <button :disabled="loading" @click="loadData(true)">{{ loading ? '读取中' : '刷新看板' }}</button>
      </div>
    </header>

    <div v-if="error" class="state error">{{ error }}</div>
    <div v-else-if="loading" class="state">正在读取预聚合质控数据...</div>

    <section class="risk-strip">
      <div class="risk-card overall" :class="risk.overall_status">
        <span class="label">整体风险</span>
        <strong>{{ overallText }}</strong>
        <p>{{ risk.headline || '按当前状态阈值综合判断' }}</p>
      </div>
      <div class="risk-card">
        <span class="label">严重异常指标</span>
        <strong>{{ risk.counts?.danger || 0 }}</strong>
        <p>超过异常阈值，需要优先核查的指标数。</p>
      </div>
      <div class="risk-card">
        <span class="label">预警指标</span>
        <strong>{{ risk.counts?.warn || 0 }}</strong>
        <p>未达最佳范围，但尚未进入严重异常的指标数。</p>
      </div>
      <div class="risk-card">
        <span class="label">AI 待办</span>
        <strong>{{ aiTodoCount }}</strong>
        <p>疑似线索和低置信度判定合计，需人工复核。</p>
      </div>
      <div class="risk-card">
        <span class="label">三管疑似线索</span>
        <strong>{{ ai.tri_tube?.count || 0 }}</strong>
        <p>AI识别的待确认线索，不等同确诊感染。</p>
      </div>
      <div class="risk-card">
        <span class="label">低置信度判定</span>
        <strong>{{ ai.low_confidence?.count || 0 }}</strong>
        <p>抗菌药用药目的 AI 判断信心不足的记录。</p>
      </div>
    </section>

    <div class="explain-bar">
      {{ risk.explain || '异常和预警均按状态配置中的阈值判定。' }}
      <span>{{ ai.explain || 'AI待办仅作质控线索提示。' }}</span>
    </div>

    <section class="kpi-row">
      <div v-for="c in kpiList" :key="c.code" class="kpi-card" :class="c.status">
        <div class="kpi-top">
          <span class="kpi-code">{{ displayCode(c.code) }}</span>
          <span class="kpi-status">{{ statusText(c.status) }}</span>
        </div>
        <div class="kpi-name">{{ c.name }}</div>
        <div class="kpi-basis">{{ thresholdHint(c.code) }}</div>
        <div class="kpi-value">
          <span>{{ fmtValue(c.value) }}</span><small>{{ c.unit }}</small>
        </div>
        <div class="kpi-sub">分子 {{ fmtCount(c.numerator) }} / 分母 {{ fmtCount(c.denominator) }}</div>
        <button class="kpi-guide" @click="guideVisible=true">口径说明</button>
      </div>
    </section>

    <section class="main-grid">
      <div class="panel abnormal-panel">
        <div class="panel-title">异常指标清单</div>
        <div v-if="abnormalList.length" class="abnormal-list">
          <div v-for="a in abnormalList" :key="a.code" class="abnormal-item" :class="a.status">
            <div class="ab-main">
              <span class="ab-code">{{ displayCode(a.code) }}</span>
              <strong>{{ a.name }}</strong>
              <span class="ab-status">{{ statusText(a.status) }}</span>
            </div>
            <div class="ab-meta">
              当前 {{ fmtValue(a.value) }}{{ a.unit }} · 分子 {{ a.numerator ?? '/' }} / 分母 {{ a.denominator ?? '/' }}
              <span v-if="a.delta != null"> · 区间变化 {{ a.delta > 0 ? '+' : '' }}{{ a.delta }}</span>
            </div>
            <div class="ab-hint">{{ a.hint }}</div>
          </div>
        </div>
        <div v-else class="empty">当前范围暂无异常或预警指标。</div>
      </div>

      <div class="panel ai-panel-wrap">
        <AiPanel :analysis="ai" />
      </div>

      <div class="panel">
        <div class="panel-title">感染发病率监测</div>
        <ControlChart name="VAP" :data="trendData['ICU-16']" :months="months" :ucl="15" unit="‰" />
        <ControlChart name="CRBSI" :data="trendData['ICU-17']" :months="months" :ucl="5" unit="‰" />
        <ControlChart name="CAUTI" :data="trendData['CAUTI']" :months="months" :ucl="5" unit="‰" />
      </div>

      <div class="panel">
        <div class="panel-title">感染性休克 Bundle</div>
        <div class="bundle-row">
          <div v-for="b in bundleItems" :key="b.code" class="bundle-item" :class="b.status">
            <span>{{ b.label }}</span>
            <strong>{{ fmtValue(b.value) }}%</strong>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-title">重点流程达标率</div>
        <div class="gauge-grid">
          <GaugeChart v-for="g in processGauges" :key="g.code"
            :name="g.shortName" :value="g.value" :unit="g.unit" :status="g.status" />
        </div>
      </div>

      <div class="panel">
        <div class="panel-title">人力配置与 SMR</div>
        <BarTargetChart :items="ratioItems" />
        <SmrChart :current="smrCurrent" :history="smrHistory" :months="months" />
      </div>
    </section>

    <Modal v-if="guideVisible" title="指标口径说明" @close="guideVisible=false">
      <IndicatorGuideModal />
    </Modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue';
import { INDICATORS, getStatusConfig, statusText as getStatusLabel } from '../config/indicators.js';
import { fetchCommandCenter, fetchDepartments } from '../api/index.js';
import GaugeChart from '../components/GaugeChart.vue';
import ControlChart from '../components/ControlChart.vue';
import AiPanel from '../components/AiPanel.vue';
import BarTargetChart from '../components/BarTargetChart.vue';
import SmrChart from '../components/SmrChart.vue';
import Modal from '../components/Modal.vue';
import IndicatorGuideModal from '../components/IndicatorGuideModal.vue';

const year = ref(2026);
const sMonth = ref(6);
const eMonth = ref(6);
const dept = ref('all');
const years = [2024, 2025, 2026];
const departments = ref([]);
const rows = ref([]);
const rowsByCode = ref({});
const values = ref({});
const trendData = ref({});
const months = ref([]);
const risk = ref({ overall_status: 'unknown', counts: {} });
const abnormal = ref([]);
const ai = ref({ summary: '', hints: [], todos: [], tri_tube: {}, low_confidence: {} });
const loading = ref(false);
const error = ref('');
const updatedAt = ref('');
const statusConfig = ref(getStatusConfig());
const guideVisible = ref(false);

const ps = computed(() => `${year.value}-${String(sMonth.value).padStart(2, '0')}`);
const pe = computed(() => `${year.value}-${String(eMonth.value).padStart(2, '0')}`);
const endPeriodParam = computed(() => sMonth.value === eMonth.value ? '' : pe.value);

function displayCode(code) {
  return INDICATORS.find(i => i.code === code)?.displayCode || code;
}
function statusText(status) {
  return getStatusLabel(status, statusConfig.value);
}
function fmtValue(v) {
  return v == null || Number.isNaN(Number(v)) ? '/' : v;
}
function fmtCount(v) {
  if (v == null || Number.isNaN(Number(v))) return '/';
  const n = Number(v);
  return Number.isInteger(n) ? n : Number(n.toFixed(3));
}
function thresholdHint(code) {
  const ind = INDICATORS.find(i => i.code === code);
  const cfg = statusConfig.value.thresholds?.[code];
  const thresholds = cfg?.thresholds || ind?.thresholds;
  const direction = cfg?.direction || ind?.direction;
  if (!thresholds?.good || !thresholds?.warn) return '按状态配置阈值判定';
  const good = thresholds.good;
  const warn = thresholds.warn;
  if (direction === 'lower_better') {
    return `达标 <=${good[1]}，预警 <=${warn[1]}，超过为异常`;
  }
  if (direction === 'higher_better') {
    return `达标 >=${good[0]}，预警 >=${warn[0]}，低于为异常`;
  }
  return `达标 ${good[0]}-${good[1]}，预警 ${warn[0]}-${warn[1]}，超出为异常`;
}
function rowItem(code, shortName = '') {
  const row = rowsByCode.value[code];
  if (!row || row.value == null) return null;
  return { ...row, shortName: shortName || row.name };
}

const kpiCodes = ['ICU-01', 'ICU-04', 'ICU-06', 'ICU-11', 'ICU-16', 'ICU-17', 'CAUTI', 'ICU-19'];
const kpiList = computed(() => kpiCodes.map(code => rowItem(code)).filter(Boolean));
const aiTodoCount = computed(() => (ai.value.todos || []).reduce((sum, item) => sum + (item.count || 0), 0));
const overallText = computed(() => {
  if (risk.value.overall_status === 'danger') return '异常';
  if (risk.value.overall_status === 'warn') return '预警';
  if (risk.value.overall_status === 'good') return '平稳';
  return '待刷新';
});
const abnormalList = computed(() => (abnormal.value || []).filter(i => i.status !== 'unknown').slice(0, 8));
const bundleItems = computed(() => ['ICU-05-1h', 'ICU-05-3h', 'ICU-05-6h'].map(code => {
  const row = rowsByCode.value[code] || {};
  return { code, label: code.replace('ICU-05-', ''), value: row.value, status: row.status || 'unknown' };
}));
const processGauges = computed(() => [
  rowItem('ICU-06', '送检率'),
  rowItem('ICU-07', 'DVT预防'),
  rowItem('ICU-09', '镇痛评估'),
  rowItem('ICU-10', '镇静评估'),
  rowItem('ICU-18', '意识评估'),
  rowItem('ICU-19', 'EN启动'),
].filter(Boolean));
const ratioItems = computed(() => [
  { name: '医生床位比', value: values.value['ICU-02'] ?? 0, target: 0.8 },
  { name: '护士床位比', value: values.value['ICU-03'] ?? 0, target: 2.5 },
]);
const smrCurrent = computed(() => values.value['ICU-11'] ?? 1);
const smrHistory = computed(() => trendData.value['ICU-11'] ?? []);

async function loadData(nocache = false) {
  if (eMonth.value < sMonth.value) eMonth.value = sMonth.value;
  loading.value = true;
  error.value = '';
  try {
    const res = await fetchCommandCenter(ps.value, endPeriodParam.value, dept.value, nocache);
    rows.value = res.rows || [];
    rowsByCode.value = Object.fromEntries(rows.value.map(r => [r.code, r]));
    values.value = res.values || {};
    trendData.value = res.trend || {};
    months.value = res.months || [];
    risk.value = res.risk || { overall_status: 'unknown', counts: {} };
    abnormal.value = res.abnormal || [];
    ai.value = res.ai || { summary: '', hints: [], todos: [] };
    updatedAt.value = res.updated_at ? res.updated_at.replace('T', ' ') : '';
  } catch (e) {
    error.value = e.message || '大屏数据读取失败';
    rows.value = [];
    rowsByCode.value = {};
    values.value = {};
    trendData.value = {};
    abnormal.value = [];
  } finally {
    loading.value = false;
  }
}

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
  window.addEventListener('status-config-updated', () => {
    statusConfig.value = getStatusConfig();
  });
  syncFromURL();
  try { departments.value = await fetchDepartments(); } catch { departments.value = []; }
  await loadData();
});
</script>

<style scoped>
.dashboard { padding:18px 24px 28px; min-height:100vh; background:#f4f6fa; color:#1e293b; }
.db-header { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:14px; }
.eyebrow { font-size:12px; color:#2563eb; font-weight:700; margin-bottom:4px; }
h1 { margin:0; font-size:22px; letter-spacing:0; }
.meta { margin-top:5px; font-size:12px; color:#64748b; }
.filters { display:flex; align-items:center; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
.filters select { background:#fff; color:#1e293b; border:1px solid #dbe4ef; border-radius:6px;
  padding:6px 10px; font-size:13px; }
.filters span { color:#64748b; font-size:12px; }
.filters button { background:#2563eb; color:#fff; border:0; border-radius:6px; padding:7px 14px;
  font-size:13px; cursor:pointer; }
.filters button.secondary { background:#fff; color:#1e3a5f; border:1px solid #cbd5e1; }
.filters button.secondary:hover { background:#eff6ff; border-color:#93c5fd; color:#1d4ed8; }
.filters button:disabled { opacity:.65; cursor:not-allowed; }
.state { margin-bottom:12px; padding:10px 12px; border-radius:8px; background:#eff6ff;
  color:#1d4ed8; font-size:13px; border:1px solid #bfdbfe; }
.state.error { background:#fef2f2; color:#b91c1c; border-color:#fecaca; }

.risk-strip { display:grid; grid-template-columns:1.35fr repeat(5,1fr); gap:10px; margin-bottom:12px; }
.risk-card { background:#fff; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px; }
.risk-card .label { display:block; color:#64748b; font-size:12px; margin-bottom:5px; }
.risk-card strong { font-size:24px; color:#0f172a; }
.risk-card p { margin:6px 0 0; color:#64748b; font-size:12px; line-height:1.45; }
.risk-card.overall.good { border-left:4px solid #16a34a; }
.risk-card.overall.warn { border-left:4px solid #d97706; }
.risk-card.overall.danger { border-left:4px solid #dc2626; }
.explain-bar { margin:-2px 0 12px; color:#475569; background:#fff; border:1px solid #dbe4ef;
  border-radius:8px; padding:10px 12px; font-size:13px; line-height:1.6; }
.explain-bar span { display:block; color:#64748b; font-size:12px; margin-top:2px; }

.kpi-row { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:12px; }
.kpi-card { background:#fff; border:1px solid #e2e8f0; border-left:4px solid #cbd5e1; border-radius:8px; padding:12px; }
.kpi-card.good { border-left-color:#16a34a; }
.kpi-card.warn { border-left-color:#d97706; }
.kpi-card.danger { border-left-color:#dc2626; }
.kpi-card.unknown { border-left-color:#94a3b8; }
.kpi-top { display:flex; justify-content:space-between; gap:8px; align-items:center; margin-bottom:5px; }
.kpi-code { color:#2563eb; font-size:12px; font-weight:700; }
.kpi-status { color:#64748b; font-size:12px; }
.kpi-name { color:#475569; font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.kpi-basis { margin-top:5px; color:#64748b; font-size:12px; line-height:1.45; min-height:18px; }
.kpi-value { margin-top:6px; display:flex; align-items:baseline; gap:3px; }
.kpi-value span { font-size:26px; font-weight:800; color:#0f172a; }
.kpi-value small { color:#64748b; }
.kpi-sub { margin-top:4px; color:#64748b; font-size:12px; }
.kpi-guide { margin-top:8px; background:#f8fafc; border:1px solid #dbe4ef; border-radius:6px;
  color:#2563eb; font-size:12px; padding:5px 8px; cursor:pointer; }
.kpi-guide:hover { background:#eff6ff; border-color:#93c5fd; }

.main-grid { display:grid; grid-template-columns:1.2fr 1fr 1fr; gap:12px; }
.panel { background:#fff; border:1px solid #e2e8f0; border-radius:8px; padding:13px 14px;
  box-shadow:0 1px 3px rgba(15,23,42,.04); min-width:0; }
.panel-title { font-size:14px; color:#1d4ed8; font-weight:700; margin-bottom:10px; padding-left:8px;
  border-left:3px solid #2563eb; }
.abnormal-panel { grid-row:span 2; }
.ai-panel-wrap { grid-row:span 2; }
.abnormal-list { display:flex; flex-direction:column; gap:8px; max-height:560px; overflow:auto; padding-right:2px; }
.abnormal-item { border:1px solid #e2e8f0; border-radius:8px; padding:10px 11px; background:#fff; }
.abnormal-item.danger { background:#fff7f7; border-color:#fecaca; }
.abnormal-item.warn { background:#fffbeb; border-color:#fde68a; }
.ab-main { display:flex; align-items:center; gap:8px; min-width:0; }
.ab-code { color:#2563eb; font-weight:700; font-size:12px; }
.ab-main strong { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:13px; }
.ab-status { font-size:12px; color:#64748b; }
.ab-meta { margin-top:6px; color:#64748b; font-size:12px; line-height:1.5; }
.ab-hint { margin-top:5px; color:#334155; font-size:12px; line-height:1.5; }
.empty { color:#94a3b8; font-size:13px; padding:20px; text-align:center; background:#f8fafc;
  border:1px dashed #cbd5e1; border-radius:8px; }
.bundle-row { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; padding:8px 0; }
.bundle-item { border:1px solid #e2e8f0; border-radius:8px; padding:16px 12px; text-align:center; }
.bundle-item span { display:block; color:#64748b; font-size:13px; margin-bottom:6px; }
.bundle-item strong { font-size:26px; color:#0f172a; }
.bundle-item.good strong { color:#16a34a; }
.bundle-item.warn strong { color:#d97706; }
.bundle-item.danger strong { color:#dc2626; }
.gauge-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:4px; }

@media (max-width: 1200px) {
  .risk-strip { grid-template-columns:repeat(3,1fr); }
  .kpi-row { grid-template-columns:repeat(2,1fr); }
  .main-grid { grid-template-columns:1fr; }
}
</style>
