<template>
  <div class="dashboard" data-theme="dark">
    <header class="db-header">
      <div class="db-header-left">
        <div class="db-brand">
          <span class="brand-cross">✚</span>
          <div>
            <span class="brand-name">ICU 医疗质量控制中心</span>
            <span class="brand-sub">实时大屏看板</span>
          </div>
        </div>
      </div>
      <div class="db-header-right">
        <div class="filters">
          <select v-model.number="year" @change="loadData">
            <option v-for="y in years" :key="y" :value="y">{{ y }}年</option>
          </select>
          <select v-model.number="sMonth" @change="loadData">
            <option v-for="m in 12" :key="m" :value="m">{{ m }}月</option>
          </select>
          <select v-model.number="eMonth" @change="loadData">
            <option v-for="m in 12" :key="m" :value="m">{{ m }}月</option>
          </select>
        </div>
        <div class="header-actions">
          <button class="action-pill" @click="guideVisible=true">指标说明</button>
          <span class="status-pill" :class="risk.overall_status">状态{{ overallText }}</span>
          <button class="action-pill icon-only" @click="loadData(true)" :disabled="loading">🔄</button>
          <span v-if="updatedAt" class="meta-update">最后更新: {{ updatedAt }}</span>
        </div>
      </div>
    </header>

    <div v-if="error" class="state error">{{ error }}</div>
    <div v-else-if="loading" class="state">正在读取预聚合质控数据...</div>

    <!-- 6 KPI Stat Cards -->
    <section class="kpi-stats">
      <div class="kpi-stat-card" :class="risk.overall_status">
        <div class="kpi-card-left" :class="risk.overall_status"></div>
        <div class="kpi-card-body">
          <div class="kpi-card-top">
            <span class="kpi-card-label">异常风险</span>
            <span class="kpi-card-icon">⚠️</span>
          </div>
          <strong class="kpi-card-big" :class="risk.overall_status">{{ overallText }}</strong>
          <div class="kpi-card-delta">较昨日 <em :class="risk.counts?.danger > 0 ? 'up' : 'flat'">{{ risk.counts?.danger > 0 ? '↑ ' + (risk.counts?.danger || 0) : '— 0' }}</em></div>
          <span class="kpi-card-desc">{{ risk.headline || '异常事件需关注，建议及时处理' }}</span>
        </div>
      </div>
      <div class="kpi-stat-card">
        <div class="kpi-card-left danger-accent"></div>
        <div class="kpi-card-body">
          <div class="kpi-card-top">
            <span class="kpi-card-label">严重异常指标</span>
            <span class="kpi-card-icon">🔴</span>
          </div>
          <strong class="kpi-card-big">{{ risk.counts?.danger || 0 }}</strong>
          <div class="kpi-card-delta">较昨日 <em :class="(risk.counts?.danger||0)>0 ? 'up' : 'flat'">{{ (risk.counts?.danger||0)>0 ? '↑ ' + risk.counts.danger : '— 0' }}</em></div>
          <span class="kpi-card-desc">涉及 ICU 床医比、ICU 护士床比</span>
        </div>
      </div>
      <div class="kpi-stat-card">
        <div class="kpi-card-left warn-accent"></div>
        <div class="kpi-card-body">
          <div class="kpi-card-top">
            <span class="kpi-card-label">预警指标</span>
            <span class="kpi-card-icon">🔔</span>
          </div>
          <strong class="kpi-card-big">{{ risk.counts?.warn || 0 }}</strong>
          <div class="kpi-card-delta">较昨日 <em class="flat">— 0</em></div>
          <span class="kpi-card-desc">暂无预警指标</span>
        </div>
      </div>
      <div class="kpi-stat-card">
        <div class="kpi-card-left ai-accent"></div>
        <div class="kpi-card-body">
          <div class="kpi-card-top">
            <span class="kpi-card-label">AI 总结</span>
            <span class="kpi-card-icon">🤖</span>
          </div>
          <strong class="kpi-card-big">{{ aiTodoCount }}</strong>
          <div class="kpi-card-delta">较昨日 <em class="flat">— 0</em></div>
          <span class="kpi-card-desc">AI未识别到需重点关注问题</span>
        </div>
      </div>
      <div class="kpi-stat-card">
        <div class="kpi-card-left sentinel-accent"></div>
        <div class="kpi-card-body">
          <div class="kpi-card-top">
            <span class="kpi-card-label">哨兵事件</span>
            <span class="kpi-card-icon">🛡️</span>
          </div>
          <strong class="kpi-card-big">0</strong>
          <div class="kpi-card-delta">较昨日 <em class="flat">— 0</em></div>
          <span class="kpi-card-desc">暂无哨兵事件报告</span>
        </div>
      </div>
      <div class="kpi-stat-card">
        <div class="kpi-card-left low-accent"></div>
        <div class="kpi-card-body">
          <div class="kpi-card-top">
            <span class="kpi-card-label">低价值评估</span>
            <span class="kpi-card-icon">📊</span>
          </div>
          <strong class="kpi-card-big">{{ ai.low_confidence?.count || 0 }}</strong>
          <div class="kpi-card-delta">较昨日 <em class="flat">— 0</em></div>
          <span class="kpi-card-desc">暂无低价值评估项目</span>
        </div>
      </div>
    </section>

    <div class="explain-bar">
      <span class="explain-main">{{ risk.explain || '异常和预警均按状态配置中的阈值判定。' }}</span>
      <span class="explain-sub">{{ ai.explain || 'AI待办仅作质控线索提示。' }}</span>
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

    <!-- 患者动态 KPI 卡 -->
    <section v-if="censusData" class="census-strip">
      <div class="census-kpi">
        <span class="c-label">原有患者</span>
        <strong>{{ censusData.carry_in }}</strong>
        <p>期初 0 点已在科</p>
      </div>
      <div class="census-kpi">
        <span class="c-label">新入患者</span>
        <strong>{{ censusData.new_admit }}</strong>
        <p>统计期内新入</p>
      </div>
      <div class="census-kpi">
        <span class="c-label">出科患者</span>
        <strong>{{ censusData.discharge }}</strong>
        <p>统计期内出科</p>
      </div>
      <div class="census-kpi">
        <span class="c-label">期末在科</span>
        <strong>{{ censusData.carry_out }}</strong>
        <p>原有 + 新入 - 出科</p>
      </div>
      <div class="census-kpi">
        <span class="c-label">同期总数</span>
        <strong>{{ censusData.total }}</strong>
        <p>原有 + 新入</p>
      </div>
      <div class="census-kpi chart-kpi">
        <CensusStackChart :trend="censusTrend" />
      </div>
    </section>

    <section class="main-grid">
      <div class="panel abnormal-panel">
        <div class="panel-title"><span class="panel-icon">☰</span> 异常指标清单</div>
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
        <div v-else class="empty">当前范围内暂无异常或预警指标。</div>
      </div>

      <div class="panel ai-panel-wrap">
        <AiPanel :analysis="ai" />
      </div>

      <div class="panel">
        <div class="panel-title"><span class="panel-icon">📈</span> 感染发病率监测</div>
        <ControlChart name="VAP" :data="trendData['ICU-16']" :months="months" :ucl="15" unit="‰" />
        <ControlChart name="CRBSI" :data="trendData['ICU-17']" :months="months" :ucl="5" unit="‰" />
        <ControlChart name="CAUTI" :data="trendData['CAUTI']" :months="months" :ucl="5" unit="‰" />
      </div>

      <div class="panel">
        <div class="panel-title"><span class="panel-icon">⏱</span> 感染性休克 Bundle</div>
        <div class="bundle-row">
          <div v-for="b in bundleItems" :key="b.code" class="bundle-item" :class="b.status">
            <span>{{ b.label }}</span>
            <strong>{{ fmtValue(b.value) }}%</strong>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-title"><span class="panel-icon">◉</span> 重点流程达标率</div>
        <div class="gauge-grid">
          <GaugeChart v-for="g in processGauges" :key="g.code"
            :name="g.shortName" :value="g.value" :unit="g.unit" :status="g.status" />
        </div>
      </div>

      <div class="panel">
        <div class="panel-title"><span class="panel-icon">👥</span> 人力配置与 SMR</div>
        <BarTargetChart :items="ratioItems" />
        <SmrChart :current="smrCurrent" :history="smrHistory" :months="months" />
      </div>
    </section>

    <!-- 底部免责声明 -->
    <footer class="db-footer">
      <div class="footer-left">
        <span class="footer-icon">ℹ️</span>
        数据来源：医院信息系统（HIS）| ICU质量管理系统（ICU-QMS）
      </div>
      <div class="footer-right">
        <span class="footer-icon">ℹ️</span>
        本看板数据仅供医疗质量管理参考，不作为临床决策依据
      </div>
    </footer>

    <Modal v-if="guideVisible" title="指标口径说明" @close="guideVisible=false">
      <IndicatorGuideModal />
    </Modal>
  </div>
</template>

<script setup>
import { ref, computed, inject, onMounted, watch } from 'vue';
import { INDICATORS, getStatusConfig, statusText as getStatusLabel } from '../config/indicators.js';
import { fetchCommandCenter } from '../api/index.js';
import GaugeChart from '../components/GaugeChart.vue';
import ControlChart from '../components/ControlChart.vue';
import AiPanel from '../components/AiPanel.vue';
import CensusStackChart from '../components/CensusStackChart.vue';
import BarTargetChart from '../components/BarTargetChart.vue';
import SmrChart from '../components/SmrChart.vue';
import Modal from '../components/Modal.vue';
import IndicatorGuideModal from '../components/IndicatorGuideModal.vue';

const year = ref(2026);
const sMonth = ref(6);
const eMonth = ref(6);
const hostDeptCode = inject('hostDeptCode', ref('all'));
const dept = computed(() => hostDeptCode.value || 'all');
const years = [2024, 2025, 2026];

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
const censusData = ref(null);
const censusTrend = ref([]);

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
const abnormalList = computed(() => (abnormal.value || []).filter(i => {
    if (i.status === 'unknown') return false;
    const ind = INDICATORS.find(x => x.code === i.code);
    return !ind?.excludeFromAlert;
  }).slice(0, 8));
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
    censusData.value = res.census || null;
    censusTrend.value = res.census_trend || [];
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
  // deptCode comes from postMessage
  const y = p.get('year'); if (y) year.value = +y;
  const sm = p.get('sMonth'); if (sm) sMonth.value = +sm;
  const em = p.get('eMonth'); if (em) eMonth.value = +em;
}
function syncToURL() {
  const u = new URL(window.location);
  // deptCode managed by postMessage
  u.searchParams.set('year', year.value);
  u.searchParams.set('sMonth', sMonth.value);
  u.searchParams.set('eMonth', eMonth.value);
  window.history.replaceState({}, '', u);
}
watch([year, sMonth, eMonth], syncToURL);

watch(hostDeptCode, () => { loadData(true); });
onMounted(async () => {
  window.addEventListener('status-config-updated', () => {
    statusConfig.value = getStatusConfig();
  });
  syncFromURL();

  await loadData();
});
</script>

<style scoped>
.dashboard {
  padding: 18px 24px 0;
  min-height: 100vh;
  background: #0b1120;
  color: #e2e8f0;
}
.db-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
  gap: 16px;
  flex-wrap: wrap;
}
.db-header-left { display: flex; align-items: center; gap: 16px; }
.db-brand { display: flex; align-items: center; gap: 10px; }
.brand-cross { font-size: 22px; color: var(--brand); }
.brand-name { display: block; font-size: 16px; font-weight: 700; color: #e2e8f0; }
.brand-sub { display: block; font-size: 12px; color: #94a3b8; margin-top: 2px; }
.db-header-right { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; justify-content: flex-end; }
.filters { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.filters select {
  background: #131c31; color: #e2e8f0; border: 1px solid #1e293b;
  border-radius: 6px; padding: 6px 10px; font-size: 13px;
}
.filters select:focus { border-color: var(--brand); outline: none; }
.header-actions { display: flex; align-items: center; gap: 8px; }
.action-pill {
  padding: 6px 14px; border-radius: 6px; border: 1px solid #1e293b;
  background: #131c31; color: #e2e8f0; font-size: 12px; cursor: pointer;
}
.action-pill:hover { background: #1a2540; border-color: var(--brand); }
.action-pill.icon-only { padding: 6px 10px; }
.action-pill:disabled { opacity: .5; cursor: not-allowed; }
.status-pill {
  padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: 600;
  background: rgba(43,94,167,0.15); color: var(--brand); border: 1px solid rgba(43,94,167,0.3);
}
.status-pill.danger { background: rgba(217,83,79,0.15); color: #D9534F; border-color: rgba(217,83,79,0.3); }
.status-pill.warn { background: rgba(232,165,61,0.15); color: #E8A53D; border-color: rgba(232,165,61,0.3); }
.meta-update { color: #64748b; font-size: 11px; white-space: nowrap; }

.state {
  margin-bottom: 12px; padding: 10px 12px; border-radius: 8px;
  background: rgba(43,94,167,0.1); color: #94a3b8; font-size: 13px;
  border: 1px solid rgba(43,94,167,0.2);
}
.state.error { background: rgba(217,83,79,0.1); color: #D9534F; border-color: rgba(217,83,79,0.2); }

/* KPI Stat Cards (top 6) */
.kpi-stats {
  display: grid; grid-template-columns: repeat(6, 1fr);
  gap: 12px; margin-bottom: 14px;
}
.kpi-stat-card {
  display: flex; background: #131c31; border: 1px solid #1e293b;
  border-radius: 10px; overflow: hidden; transition: transform .15s;
}
.kpi-stat-card:hover { transform: translateY(-2px); }
.kpi-card-left { width: 4px; flex-shrink: 0; background: #64748b; }
.kpi-card-left.danger-accent { background: #D9534F; }
.kpi-card-left.warn-accent { background: #E8A53D; }
.kpi-card-left.ai-accent { background: #6366f1; }
.kpi-card-left.sentinel-accent { background: #2B5EA7; }
.kpi-card-left.low-accent { background: #94a3b8; }
.kpi-stat-card.danger .kpi-card-left { background: #D9534F; }
.kpi-stat-card.danger .kpi-card-big { color: #D9534F; }
.kpi-stat-card.warn .kpi-card-left { background: #E8A53D; }
.kpi-stat-card.warn .kpi-card-big { color: #E8A53D; }
.kpi-stat-card.good .kpi-card-left { background: #2B5EA7; }
.kpi-card-body { padding: 12px 14px; flex: 1; min-width: 0; }
.kpi-card-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.kpi-card-label { font-size: 12px; color: #94a3b8; }
.kpi-card-icon { font-size: 16px; }
.kpi-card-big { display: block; font-size: 28px; color: #e2e8f0; margin-bottom: 4px; }
.kpi-card-delta { font-size: 11px; color: #64748b; margin-bottom: 4px; }
.kpi-card-delta em { font-style: normal; }
.kpi-card-delta em.up { color: #D9534F; }
.kpi-card-delta em.flat { color: #64748b; }
.kpi-card-desc { display: block; font-size: 11px; color: #475569; line-height: 1.4; }

/* Explain bar */
.explain-bar {
  margin: -2px 0 14px; color: #94a3b8; background: #131c31;
  border: 1px solid #1e293b; border-radius: 8px; padding: 10px 14px;
  font-size: 13px; line-height: 1.6;
}
.explain-main { color: #94a3b8; }
.explain-sub { display: block; color: #64748b; font-size: 12px; margin-top: 2px; }

/* KPI detail row */
.kpi-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px; }
.kpi-card {
  background: #131c31; border: 1px solid #1e293b;
  border-left: 4px solid #475569; border-radius: 10px; padding: 14px;
}
.kpi-card.good { border-left-color: #2B5EA7; }
.kpi-card.warn { border-left-color: #E8A53D; }
.kpi-card.danger { border-left-color: #D9534F; }
.kpi-card.unknown { border-left-color: #475569; }
.kpi-top { display: flex; justify-content: space-between; gap: 8px; align-items: center; margin-bottom: 5px; }
.kpi-code { color: var(--brand); font-size: 12px; font-weight: 700; }
.kpi-status { color: #94a3b8; font-size: 12px; }
.kpi-name { color: #cbd5e1; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kpi-basis { margin-top: 5px; color: #64748b; font-size: 12px; line-height: 1.45; min-height: 18px; }
.kpi-value { margin-top: 6px; display: flex; align-items: baseline; gap: 3px; }
.kpi-value span { font-size: 26px; font-weight: 800; color: #e2e8f0; }
.kpi-value small { color: #64748b; }
.kpi-sub { margin-top: 4px; color: #64748b; font-size: 12px; }
.kpi-guide {
  margin-top: 8px; background: rgba(43,94,167,0.1);
  border: 1px solid rgba(43,94,167,0.3); border-radius: 6px;
  color: var(--brand); font-size: 12px; padding: 5px 8px; cursor: pointer;
}
.kpi-guide:hover { background: rgba(43,94,167,0.2); }

/* Census strip */
.census-strip { display: grid; grid-template-columns: repeat(4, 1fr) 2fr; gap: 10px; margin-bottom: 14px; }
.census-kpi { background: #131c31; border: 1px solid #1e293b; border-radius: 10px; padding: 12px 14px; }
.census-kpi .c-label { display: block; color: #94a3b8; font-size: 12px; margin-bottom: 5px; }
.census-kpi strong { font-size: 24px; color: #e2e8f0; }
.census-kpi p { margin: 6px 0 0; color: #64748b; font-size: 12px; line-height: 1.45; }
.census-kpi.chart-kpi { background: transparent; border: none; padding: 0; }

/* Main grid */
.main-grid { display: grid; grid-template-columns: 1.2fr 1fr 1fr; gap: 12px; }
.panel {
  background: #131c31; border: 1px solid #1e293b; border-radius: 10px;
  padding: 14px 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.2); min-width: 0;
}
.panel-title {
  font-size: 14px; color: var(--brand); font-weight: 700;
  margin-bottom: 12px; padding-left: 8px; border-left: 3px solid var(--brand);
  display: flex; align-items: center; gap: 6px;
}
.panel-icon { font-size: 14px; opacity: .7; }
.abnormal-panel { grid-row: span 2; }
.ai-panel-wrap { grid-row: span 2; }
.abnormal-list { display: flex; flex-direction: column; gap: 8px; max-height: 560px; overflow: auto; padding-right: 2px; }
.abnormal-item {
  border: 1px solid #1e293b; border-radius: 8px; padding: 12px;
  background: #0f1729; transition: background .15s;
}
.abnormal-item:hover { background: #1a2540; }
.abnormal-item.danger { background: rgba(217,83,79,0.06); border-color: rgba(217,83,79,0.25); }
.abnormal-item.warn { background: rgba(232,165,61,0.06); border-color: rgba(232,165,61,0.25); }
.ab-main { display: flex; align-items: center; gap: 8px; min-width: 0; }
.ab-code { color: var(--brand); font-weight: 700; font-size: 12px; }
.ab-main strong { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; color: #e2e8f0; }
.ab-status { font-size: 12px; color: #94a3b8; }
.ab-meta { margin-top: 6px; color: #64748b; font-size: 12px; line-height: 1.5; }
.ab-hint { margin-top: 5px; color: #94a3b8; font-size: 12px; line-height: 1.5; }
.empty {
  color: #475569; font-size: 13px; padding: 20px; text-align: center;
  background: #0f1729; border: 1px dashed #1e293b; border-radius: 8px;
}
.bundle-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; padding: 8px 0; }
.bundle-item {
  border: 1px solid #1e293b; border-radius: 8px;
  padding: 16px 12px; text-align: center; background: #0f1729;
}
.bundle-item span { display: block; color: #94a3b8; font-size: 13px; margin-bottom: 6px; }
.bundle-item strong { font-size: 26px; color: #e2e8f0; }
.bundle-item.good strong { color: #2B5EA7; }
.bundle-item.warn strong { color: #E8A53D; }
.bundle-item.danger strong { color: #D9534F; }
.gauge-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 4px; }

/* Footer disclaimer */
.db-footer {
  display: flex; justify-content: space-between; align-items: center;
  margin-top: 16px; padding: 12px 16px; background: #0f1729;
  border: 1px solid #1e293b; border-radius: 8px; font-size: 12px; color: #64748b;
}
.footer-icon { margin-right: 4px; }

@media (max-width: 1200px) {
  .kpi-stats { grid-template-columns: repeat(3, 1fr); }
  .kpi-row { grid-template-columns: repeat(2, 1fr); }
  .main-grid { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .kpi-stats { grid-template-columns: repeat(2, 1fr); }
  .db-header { flex-direction: column; }
  .db-header-right { width: 100%; }
}
</style>