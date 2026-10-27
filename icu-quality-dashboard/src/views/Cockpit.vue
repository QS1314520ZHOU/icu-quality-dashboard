<template>
  <div class="cockpit">
    <!-- 顶栏 -->
    <header class="ck-top">
      <div class="ck-brand">
        <span class="ck-dot"></span>
        <h1>ICU 质控驾驶舱</h1>
        <span class="ck-sub">{{ hospitalName }} · {{ scopeLabel }} · 晨会投屏</span>
      </div>
      <div class="ck-controls">
        <select v-model.number="year" @change="load" aria-label="年份">
          <option v-for="y in years" :key="y" :value="y">{{ y }}年</option>
        </select>
        <select v-model.number="sMonth" @change="load" aria-label="起始月">
          <option v-for="m in 12" :key="m" :value="m">{{ m }}月</option>
        </select>
        <span class="ck-to">至</span>
        <select v-model.number="eMonth" @change="load" aria-label="结束月">
          <option v-for="m in 12" :key="m" :value="m">{{ m }}月</option>
        </select>
        <button class="ck-btn" @click="load(true)">刷新</button>
        <span v-if="updatedAt" class="ck-updated">更新 {{ updatedAt }}</span>
      </div>
    </header>

    <div v-if="error" class="ck-state error">{{ error }}</div>
    <div v-else-if="loading" class="ck-state">正在载入质控数据…</div>

    <template v-else>
      <!-- 数据缺口提示：预聚合/HIS 无数据时不再假装「一切正常」 -->
      <div v-if="dataGapCount > 0" class="ck-gap-banner">
        <span class="gap-icon">!</span>
        <span>
          本区间有 <b>{{ dataGapCount }}</b>/{{ allEvals.length || 0 }} 项指标尚未生成预聚合数据（显示为「未生成」）。
          请确认 HIS 连接正常后，到「指标管理」点击<strong>刷新数据</strong>触发补算；补算完成前驾驶舱无法给出完整偏离评估。
        </span>
        <button class="ck-btn gap-btn" @click="load(true)">立即刷新</button>
      </div>

      <!-- 顶区：关注清单 + 达标率 + 解读顺序 -->
      <section class="ck-hero">
        <div class="ck-panel action-panel">
          <div class="ck-panel-title">
            关注清单
            <span class="ck-hint">结果 → 过程 · 非红绿灯，按偏离程度排序</span>
          </div>
          <div v-if="dataGapCount > 0 && !actionList.length" class="action-empty warn-empty">
            数据尚未生成，无法计算偏离与关注清单。请先触发预聚合补算。
          </div>
          <div v-else-if="actionList.length" class="action-list">
            <div v-for="item in actionList.slice(0, 6)" :key="item.code"
                 class="action-row" :class="item.level" @click="openTrend(item)">
              <span class="lv-tag">{{ item.levelMeta.label }}</span>
              <span class="a-code">{{ displayCode(item.code) }}</span>
              <span class="a-name">{{ item.name }}</span>
              <span class="a-val tabular-nums">{{ fmtVal(item.value) }}{{ item.unit }}</span>
              <span v-if="item.numerator != null" class="a-nd tabular-nums">{{ item.numerator }}/{{ item.denominator }}</span>
              <span class="a-reason">{{ item.reason }}</span>
              <span v-if="item.spc?.special" class="spc-tag">SPC 特殊波动</span>
            </div>
            <div v-if="actionList.length > 6" class="action-more">
              另有 {{ actionList.length - 6 }} 项待复核…
            </div>
          </div>
          <div v-else class="action-empty">本期已生成数据中，结果/过程指标均在目标带内或仅轻度偏离</div>
        </div>

        <div class="ck-panel rate-panel">
          <div class="ck-panel-title">达标率总览 <span class="ck-hint">平稳项占比 · 不含未生成数据</span></div>
          <ComplianceRatePanel :zone-stats="zoneStats" :overall-counts="riskCounts" dark />
          <p class="ck-calc-note">
            达标率 = 处于目标带内的项数 ÷ 已生成数据的有效项数（排除未生成）。
            偏离分级 = 当前值与目标带的相对距离：带内为平稳；超出带宽 25% 以内轻度、50% 以内中度、以上显著。
            点击任意指标卡可打开「年度 + 月度」趋势对照图。
          </p>
        </div>
      </section>

      <!-- 结果区（优先解读） -->
      <section class="ck-section">
        <div class="ck-sec-head">
          <h2>① 结果质量</h2>
          <span class="ck-sec-note">先看结果：最终结局是否异常</span>
          <span class="ck-sec-stat">{{ outcomeWithData }}/{{ outcomeEvals.length }} 项有数据</span>
        </div>
        <div v-if="!outcomeEvals.length" class="ck-empty-slot">无结果类指标</div>
        <div v-else class="card-grid outcome">
          <div v-for="c in outcomeEvals" :key="c.code" class="ck-card" :class="[c.level, { missing: c.value == null }]"
               @click="openTrend(c)">
            <div class="ck-card-top">
              <span class="ck-code">{{ displayCode(c.code) }}</span>
              <span class="lv-dot" :title="c.levelMeta.label"></span>
            </div>
            <div class="ck-card-name">{{ shortName(c.name) }}</div>
            <div class="ck-card-val tabular-nums">
              {{ c.value == null ? '未生成' : fmtVal(c.value) }}<small v-if="c.value != null">{{ c.unit }}</small>
            </div>
            <div class="ck-card-foot">
              <span class="lv-label">{{ c.value == null ? '等待预聚合' : c.levelMeta.label }}</span>
              <span v-if="c.numerator != null" class="nd tabular-nums">{{ c.numerator }}/{{ c.denominator }}</span>
              <span v-if="c.spc?.special" class="spc-tag">SPC</span>
              <span v-if="c.deviation" class="dev-pct tabular-nums">偏离带 {{ Math.round(c.deviation * 100) }}%</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 过程区 -->
      <section class="ck-section">
        <div class="ck-sec-head">
          <h2>② 过程质量</h2>
          <span class="ck-sec-note">结果有问题再看过程：救治是否规范到位</span>
          <span class="ck-sec-stat">{{ processWithData }}/{{ processEvals.length }} 项有数据</span>
        </div>
        <div v-if="!processEvals.length" class="ck-empty-slot">无过程类指标</div>
        <div v-else class="card-grid process">
          <div v-for="c in processEvals" :key="c.code" class="ck-card" :class="[c.level, { missing: c.value == null }]"
               @click="openTrend(c)">
            <div class="ck-card-top">
              <span class="ck-code">{{ displayCode(c.code) }}</span>
              <span class="lv-dot" :title="c.levelMeta.label"></span>
            </div>
            <div class="ck-card-name">{{ shortName(c.name) }}</div>
            <div class="ck-card-val tabular-nums">
              {{ c.value == null ? '未生成' : fmtVal(c.value) }}<small v-if="c.value != null">{{ c.unit }}</small>
            </div>
            <div class="ck-card-foot">
              <span class="lv-label">{{ c.value == null ? '等待预聚合' : c.levelMeta.label }}</span>
              <span v-if="c.numerator != null" class="nd tabular-nums">{{ c.numerator }}/{{ c.denominator }}</span>
              <span v-if="c.spc?.special" class="spc-tag">SPC</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 结构区（默认折叠） -->
      <section class="ck-section">
        <button class="ck-sec-toggle" @click="structureOpen = !structureOpen">
          <h2>③ 结构与资源</h2>
          <span class="ck-sec-note">合理波动内无需过多关注</span>
          <span class="ck-sec-stat">{{ structureWithData }}/{{ structureEvals.length }} 项有数据</span>
          <span class="toggle-mark">{{ structureOpen ? '收起' : '展开' }}</span>
        </button>
        <div v-show="structureOpen" class="card-grid structure">
          <div v-for="c in structureEvals" :key="c.code" class="ck-card" :class="[c.level, { missing: c.value == null }]"
               @click="openTrend(c)">
            <div class="ck-card-top">
              <span class="ck-code">{{ displayCode(c.code) }}</span>
              <span class="lv-dot" :title="c.levelMeta.label"></span>
            </div>
            <div class="ck-card-name">{{ shortName(c.name) }}</div>
            <div class="ck-card-val tabular-nums">
              {{ c.value == null ? '未生成' : fmtVal(c.value) }}<small v-if="c.value != null">{{ c.unit }}</small>
            </div>
            <div class="ck-card-foot">
              <span class="lv-label">{{ c.value == null ? '等待预聚合' : c.levelMeta.label }}</span>
              <span v-if="c.numerator != null" class="nd tabular-nums">{{ c.numerator }}/{{ c.denominator }}</span>
            </div>
          </div>
        </div>
      </section>
    </template>

    <footer class="ck-footer">
      预警采用偏离度分级 + SPC 特殊波动信号，不使用红绿灯达标制 · 数据来源 HIS / ICU-QMS
    </footer>

    <!-- 趋势弹窗：文章同款 年度 + 月度 双图 -->
    <div v-if="trendOpen" class="ck-modal-mask" @click.self="trendOpen = false">
      <div class="ck-modal">
        <div class="ck-modal-bar">
          <span>{{ trendRow?.name }}</span>
          <button class="ck-btn" @click="trendOpen = false">关闭</button>
        </div>
        <DualTrend
          v-if="trendRow"
          :code="trendRow.code"
          :name="trendRow.name"
          :monthly="monthlyFor(trendRow.code)"
          :year="year"
          :icu-unit="dept"
          :status="trendRow.value == null ? '' : backendStatus(trendRow.code)"
          :kind="trendRow.kind"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, inject, onMounted, watch } from 'vue';
import { INDICATORS, getStatusConfig } from '../config/indicators.js';
import { INDICATOR_GROUPS, getGroupStats } from '../config/indicatorGroups.js';
import { fetchCommandCenter } from '../api/index.js';
import { evaluateIndicator, buildActionList, DEVIATION_META } from '../utils/deviation.js';
import ComplianceRatePanel from '../components/ComplianceRatePanel.vue';
import DualTrend from '../components/DualTrend.vue';

const hospitalName = '重庆医科大学附属第二医院';
// 与大屏总览共用宿主科室；显示科室名而非编码
const hostDeptCode = inject('hostDeptCode', ref(''));
const hostDeptName = inject('hostDeptName', ref(''));
const dept = computed(() => hostDeptCode.value || 'all');
const scopeLabel = computed(() => {
  if (dept.value === 'all') return '全部科室';
  return hostDeptName.value || `科室 ${dept.value}`;
});

const year = ref(new Date().getFullYear());
const sMonth = ref(1);
const eMonth = ref(new Date().getMonth() + 1);
const years = computed(() => {
  const arr = [];
  for (let y = 2023; y <= new Date().getFullYear(); y++) arr.push(y);
  return arr.reverse();
});

const loading = ref(false);
const error = ref('');
const updatedAt = ref('');
const rows = ref([]);
const rowsByCode = ref({});
const risk = ref({ overall_status: 'unknown', counts: {} });
const trendData = ref({});
const structureOpen = ref(false); // 结构类默认折叠
const statusConfig = ref(getStatusConfig());

const ps = computed(() => `${year.value}-${String(sMonth.value).padStart(2, '0')}`);
const endPeriodParam = computed(() => sMonth.value === eMonth.value ? '' : `${year.value}-${String(eMonth.value).padStart(2, '0')}`);

function displayCode(code) {
  return INDICATORS.find(i => i.code === code)?.displayCode || code;
}
function shortName(name) {
  return (name || '').replace(/^ICU/, '').trim();
}
function fmtVal(v) {
  if (v == null || Number.isNaN(Number(v))) return '—';
  return Math.abs(v) >= 10 ? Math.round(v * 10) / 10 : v;
}
function indicatorKind(code) {
  // 三分类：structure/process/outcome。感染防控组 kind 也是 outcome，须一并计入结果区。
  let fallback = null;
  for (const g of INDICATOR_GROUPS) {
    if (!g.codes?.includes(code)) continue;
    if (['structure', 'process', 'outcome'].includes(g.id)) return g.kind;
    if (g.kind === 'outcome' && !fallback) fallback = 'outcome';
    if (g.kind === 'process' && !fallback) fallback = 'process';
    if (g.kind === 'structure' && !fallback) fallback = 'structure';
  }
  return fallback;
}
function goodBand(code) {
  const ind = INDICATORS.find(i => i.code === code);
  const saved = statusConfig.value.thresholds?.[code]?.thresholds;
  // 本机配置不完整时回退指标默认，避免「有值却显示数据不足」
  if (Array.isArray(saved?.good) && saved.good.length === 2 && saved.good.every(v => v != null && !Number.isNaN(Number(v)))) {
    return saved.good;
  }
  return ind?.thresholds?.good || null;
}

const zoneStats = computed(() => {
  const stats = {};
  for (const g of INDICATOR_GROUPS) {
    if (['structure', 'process', 'outcome'].includes(g.id)) {
      stats[g.id] = getGroupStats(g, rowsByCode.value);
    }
  }
  return stats;
});
const riskCounts = computed(() => {
  const c = risk.value.counts || {};
  return { good: c.good || 0, warn: c.warn || 0, danger: c.danger || 0, unknown: c.unknown || 0 };
});

/** 按 kind 分组的评估结果（用偏离度体系，不用后端 status 三色） */
const allEvals = computed(() => {
  return rows.value
    .filter(r => r?.code && r.code !== 'ICU-00')
    .map(r => {
      const kind = indicatorKind(r.code);
      if (!kind) return null;
      const ev = evaluateIndicator(
        { ...r, kind },
        trendData.value[r.code],
        goodBand(r.code),
      );
      return ev;
    })
    .filter(Boolean);
});

const outcomeEvals = computed(() => allEvals.value.filter(e => e.kind === 'outcome'));
const processEvals = computed(() => allEvals.value.filter(e => e.kind === 'process'));
const structureEvals = computed(() => allEvals.value.filter(e => e.kind === 'structure'));
const actionList = computed(() => buildActionList(allEvals.value));

const dataGapCount = computed(() => allEvals.value.filter(e => e.value == null).length);
const outcomeWithData = computed(() => outcomeEvals.value.filter(e => e.value != null).length);
const processWithData = computed(() => processEvals.value.filter(e => e.value != null).length);
const structureWithData = computed(() => structureEvals.value.filter(e => e.value != null).length);

// 趋势弹窗
const trendOpen = ref(false);
const trendRow = ref(null);

function openTrend(evalRow) {
  if (!evalRow?.code) return;
  trendRow.value = { ...evalRow };
  trendOpen.value = true;
}
function monthlyFor(code) {
  const arr = trendData.value[code];
  const months = [];
  for (let m = 1; m <= 12; m++) months.push(`${m}月`);
  return { months, values: Array.isArray(arr) ? arr : [] };
}
function backendStatus(code) {
  const s = rowsByCode.value[code]?.status;
  return ['good', 'warn', 'danger'].includes(s) ? s : '';
}

async function load(nocache = false) {
  if (eMonth.value < sMonth.value) eMonth.value = sMonth.value;
  loading.value = true;
  error.value = '';
  try {
    const res = await fetchCommandCenter(ps.value, endPeriodParam.value, dept.value, nocache);
    rows.value = res.rows || [];
    rowsByCode.value = Object.fromEntries(rows.value.map(r => [r.code, r]));
    risk.value = res.risk || { overall_status: 'unknown', counts: {} };
    trendData.value = res.trend || {};
    updatedAt.value = res.updated_at ? res.updated_at.replace('T', ' ') : '';
  } catch (e) {
    error.value = e.message || '数据读取失败';
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

function onStatusConfigUpdated() {
  statusConfig.value = getStatusConfig();
}

onMounted(() => {
  load();
  window.addEventListener('status-config-updated', onStatusConfigUpdated);
  window.addEventListener('refresh-data', () => load(true));
});
watch(() => [year.value, sMonth.value, eMonth.value], () => load());
// 宿主/URL 补上科室后立即按科室重载（避免先打 all 全院再空等）
watch(dept, (nv, ov) => { if (nv !== ov) load(true); });
</script>

<style scoped>
.cockpit {
  --ck-bg: #0b1220;
  --ck-panel: #121a2b;
  --ck-border: rgba(110, 150, 210, 0.16);
  --ck-text: #e8eef8;
  --ck-sub: #8fa3c0;
  --ck-faint: #5c6f88;
  --lv-steady: #5b8def;
  --lv-mild: #d4a017;
  --lv-moderate: #e07b00;
  --lv-significant: #b5451b;
  min-height: 100%;
  background:
    radial-gradient(1200px 400px at 15% -10%, rgba(40, 90, 180, 0.25), transparent 60%),
    radial-gradient(900px 300px at 90% 0%, rgba(20, 120, 140, 0.12), transparent 55%),
    var(--ck-bg);
  color: var(--ck-text);
  padding: 16px 20px 28px;
  font-size: 14px;
}

/* 顶栏 */
.ck-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--ck-border);
}
.ck-brand { display: flex; align-items: baseline; gap: 12px; min-width: 0; }
.ck-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: #3d8bfd;
  box-shadow: 0 0 8px #3d8bfd;
  align-self: center;
}
.ck-brand h1 { font-size: 20px; font-weight: 650; margin: 0; letter-spacing: 0.02em; }
.ck-sub { font-size: 12px; color: var(--ck-sub); white-space: nowrap; }
.ck-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ck-controls select {
  background: var(--ck-panel); color: var(--ck-text);
  border: 1px solid var(--ck-border); border-radius: 6px;
  padding: 6px 8px; font-size: 13px;
}
.ck-to { color: var(--ck-faint); font-size: 12px; }
.ck-btn {
  background: rgba(61, 139, 253, 0.15);
  color: #7eb0ff;
  border: 1px solid rgba(61, 139, 253, 0.35);
  border-radius: 6px; padding: 6px 14px;
  cursor: pointer; font-size: 13px;
}
.ck-btn:hover { background: rgba(61, 139, 253, 0.28); }
.ck-updated { font-size: 11px; color: var(--ck-faint); }

.ck-state {
  padding: 48px; text-align: center; color: var(--ck-sub);
  background: var(--ck-panel); border-radius: 10px; border: 1px solid var(--ck-border);
}
.ck-state.error { color: #ff8f8f; }

/* 数据缺口横幅 */
.ck-gap-banner {
  display: flex; align-items: center; gap: 12px;
  background: rgba(212, 160, 23, 0.10);
  border: 1px solid rgba(212, 160, 23, 0.35);
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 14px;
  font-size: 13px;
  color: #e8d5a0;
  line-height: 1.5;
}
.ck-gap-banner b { color: #f0c56a; }
.gap-icon {
  width: 22px; height: 22px; border-radius: 50%;
  background: rgba(212, 160, 23, 0.25); color: #f0c56a;
  display: inline-flex; align-items: center; justify-content: center;
  font-weight: 700; flex-shrink: 0;
}
.gap-btn { margin-left: auto; flex-shrink: 0; }

.ck-sec-stat {
  font-size: 11px; color: var(--ck-faint);
  margin-left: auto;
}
.ck-empty-slot {
  padding: 24px; text-align: center;
  color: var(--ck-faint); font-size: 13px;
  background: var(--ck-panel);
  border: 1px dashed var(--ck-border);
  border-radius: 10px;
}
.ck-card.missing {
  opacity: 0.55;
  border-top-color: transparent !important;
  background: rgba(255, 255, 255, 0.02);
}
.ck-card.missing .ck-card-val { font-size: 16px; font-weight: 600; color: var(--ck-faint); }
.ck-card.missing .lv-dot { background: var(--ck-faint) !important; box-shadow: none !important; }
.warn-empty { color: #e8c56a !important; }

/* Hero */
.ck-hero {
  display: grid;
  grid-template-columns: minmax(280px, 1.1fr) minmax(320px, 1.4fr);
  gap: 14px;
  margin-bottom: 18px;
}
.ck-panel {
  background: var(--ck-panel);
  border: 1px solid var(--ck-border);
  border-radius: 12px;
  padding: 14px 16px;
}
.ck-panel-title {
  font-size: 14px; font-weight: 600;
  display: flex; align-items: baseline; gap: 10px;
  margin-bottom: 12px;
}
.ck-hint { font-size: 11px; color: var(--ck-faint); font-weight: 400; }

.action-list { display: flex; flex-direction: column; gap: 8px; }
.action-row {
  display: grid;
  grid-template-columns: auto auto 1fr auto auto auto;
  gap: 10px;
  align-items: center;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  border-left: 3px solid var(--lv-steady);
  font-size: 13px;
}
.action-row.mild { border-left-color: var(--lv-mild); }
.action-row.moderate { border-left-color: var(--lv-moderate); }
.action-row.significant { border-left-color: var(--lv-significant); }
.lv-tag {
  font-size: 11px; padding: 2px 6px; border-radius: 4px;
  background: rgba(255, 255, 255, 0.06); color: var(--ck-sub);
}
.a-code { font-size: 11px; color: var(--ck-faint); font-weight: 600; }
.a-name { color: var(--ck-text); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.a-val { font-weight: 650; color: #cfe0ff; }
.a-reason { font-size: 11px; color: var(--ck-sub); }
.spc-tag {
  font-size: 10px; padding: 2px 5px; border-radius: 3px;
  background: rgba(212, 160, 23, 0.18); color: #e8c56a;
  white-space: nowrap;
}
.action-empty, .action-more { font-size: 12px; color: var(--ck-faint); padding: 8px 4px; }

/* Section */
.ck-section { margin-bottom: 18px; }
.ck-sec-head, .ck-sec-toggle {
  display: flex; align-items: baseline; gap: 12px;
  margin-bottom: 10px;
}
.ck-sec-toggle {
  width: 100%;
  background: none; border: none; color: inherit;
  cursor: pointer; padding: 0; text-align: left;
}
.ck-sec-head h2, .ck-sec-toggle h2 {
  margin: 0; font-size: 15px; font-weight: 650; letter-spacing: 0.02em;
}
.ck-sec-note { font-size: 11px; color: var(--ck-faint); }
.toggle-mark {
  margin-left: auto; font-size: 11px; color: #7eb0ff;
  border: 1px solid rgba(61, 139, 253, 0.35);
  padding: 2px 8px; border-radius: 4px;
}

/* Cards */
.card-grid {
  display: grid;
  gap: 10px;
}
.card-grid.outcome { grid-template-columns: repeat(3, 1fr); }
.card-grid.process { grid-template-columns: repeat(4, 1fr); }
.card-grid.structure { grid-template-columns: repeat(3, 1fr); }

.ck-card {
  background: var(--ck-panel);
  border: 1px solid var(--ck-border);
  border-radius: 10px;
  padding: 12px 14px 10px;
  border-top: 2px solid transparent;
  min-width: 0;
}
.ck-card.steady { border-top-color: rgba(91, 141, 239, 0.45); }
.ck-card.mild { border-top-color: var(--lv-mild); }
.ck-card.moderate { border-top-color: var(--lv-moderate); background: rgba(224, 123, 0, 0.06); }
.ck-card.significant {
  border-top-color: var(--lv-significant);
  background: rgba(181, 69, 27, 0.12);
  box-shadow: 0 0 0 1px rgba(181, 69, 27, 0.25);
}
.ck-card-top { display: flex; justify-content: space-between; align-items: center; }
.ck-code { font-size: 10px; font-weight: 700; color: var(--ck-faint); letter-spacing: 0.04em; }
.lv-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--lv-steady);
}
.ck-card.mild .lv-dot { background: var(--lv-mild); }
.ck-card.moderate .lv-dot { background: var(--lv-moderate); }
.ck-card.significant .lv-dot { background: var(--lv-significant); box-shadow: 0 0 6px rgba(181, 69, 27, 0.8); }
.ck-card.unknown .lv-dot { background: var(--ck-faint); }

.ck-card-name {
  font-size: 12px; color: var(--ck-sub);
  margin: 4px 0 6px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.ck-card-val {
  font-size: 26px; font-weight: 700; line-height: 1.15;
  color: var(--ck-text);
}
.ck-card-val small { font-size: 12px; font-weight: 500; color: var(--ck-sub); margin-left: 2px; }
.ck-card-foot {
  display: flex; gap: 8px; align-items: center; margin-top: 8px;
  font-size: 11px; color: var(--ck-faint);
}
.lv-label { color: var(--ck-sub); }
.ck-card.significant .lv-label { color: #f0a080; }

.ck-footer {
  margin-top: 8px;
  font-size: 11px;
  color: var(--ck-faint);
  text-align: center;
}

.ck-calc-note {
  margin: 12px 0 0;
  font-size: 11px;
  line-height: 1.55;
  color: var(--ck-faint);
}
.nd, .a-nd {
  font-size: 11px;
  color: var(--ck-sub);
  background: rgba(255,255,255,0.05);
  padding: 1px 6px;
  border-radius: 4px;
}
.ck-card { cursor: pointer; }
.ck-card:hover { border-color: rgba(110, 150, 210, 0.4); }
.action-row { cursor: pointer; }
.action-row:hover { background: rgba(255, 255, 255, 0.06); }

/* 趋势弹窗 */
.ck-modal-mask {
  position: fixed; inset: 0;
  background: rgba(4, 8, 16, 0.72);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
  padding: 24px;
}
.ck-modal {
  background: var(--ck-panel);
  border: 1px solid var(--ck-border);
  border-radius: 14px;
  padding: 16px 18px 18px;
  width: min(960px, 100%);
  max-height: 90vh;
  overflow: auto;
}
.ck-modal-bar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 12px; font-weight: 600; color: var(--ck-text);
}
/* 弹窗内双图沿用浅色卡片，保证图表可读性 */
.ck-modal :deep(.dt-title strong) { color: var(--ck-text); }
.ck-modal :deep(.dt-target) {
  background: rgba(255,255,255,0.05);
  border-color: var(--ck-border);
  color: var(--ck-sub);
}
.ck-modal :deep(.dt-panel) {
  background: rgba(255,255,255,0.03);
  border-color: var(--ck-border);
}
.ck-modal :deep(.dt-panel-title) { color: var(--ck-sub); }
.ck-modal :deep(.dt-foot) { color: var(--ck-faint); }

@media (max-width: 1280px) {
  .card-grid.outcome { grid-template-columns: repeat(2, 1fr); }
  .card-grid.process { grid-template-columns: repeat(3, 1fr); }
  .ck-hero { grid-template-columns: 1fr; }
}
@media (max-width: 800px) {
  .card-grid.outcome,
  .card-grid.process,
  .card-grid.structure { grid-template-columns: 1fr 1fr; }
}
</style>
