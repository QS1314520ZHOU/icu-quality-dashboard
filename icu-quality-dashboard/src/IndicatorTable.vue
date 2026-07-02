<template>
  <div class="table-page">
    <!-- 顶部筛选条 -->
    <div class="filter-bar">
      <span class="page-title">ICU 质控指标明细 · {{ deptName }}</span>
      <div class="filters">
        <select v-model="year" @change="reload"><option v-for="y in years" :key="y" :value="y">{{ y }}年</option></select>
        <select v-model="startMonth" @change="reload"><option v-for="m in 12" :key="m" :value="m">{{ m }}月</option></select>
        <span class="dash">—</span>
        <select v-model="endMonth" @change="reload"><option v-for="m in 12" :key="m" :value="m">{{ m }}月</option></select>
        <select v-model="unit" @change="reload">
          <option value="all">全部ICU</option>
          <option v-for="d in departments" :key="d.code" :value="d.code">{{ d.name }}</option>
        </select>
        <button class="refresh-btn" :disabled="refreshing" @click="triggerRefresh">
          <span v-if="refreshing" class="spinner"></span>
          {{ refreshing ? '后台刷新中' : '刷新数据' }}
        </button>
        <button class="guide-btn" @click="guideVisible=true">指标说明</button>
        <button class="export-btn" @click="exportCsv">导出CSV</button>
      </div>
    </div>

    <div class="table-wrap" :class="{ 'multi-month': isMultiMonth }">
      <table class="indi-table">
        <colgroup>
          <col class="c-code" />
          <col class="c-name" />
          <col class="c-num" />
          <col class="c-num" />
          <col class="c-val" />
          <col v-for="m in monthCols" :key="'col'+m" class="c-month" />
          <col class="c-status" />
          <col class="c-trend" />
        </colgroup>
        <thead>
          <tr>
            <th class="t-left">编码</th>
            <th class="t-left">指标名称</th>
            <th class="t-right">分子</th>
            <th class="t-right">分母</th>
            <th class="t-right sep">比值</th>
            <th v-for="m in monthCols" :key="'h'+m" class="t-right">{{ m }}月</th>
            <th class="t-center sep">状态</th>
            <th class="t-center">趋势</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.code">
            <td class="code t-left">{{ displayCode(row.code) }}</td>
            <td class="name t-left" @mouseenter="showTip($event, row.code)" @mouseleave="hideTip">
              <span class="name-txt">{{ row.name }}</span>
              <span class="formula-icon">ƒ</span>
            </td>
            <td class="num t-right link" @click="drillDetail(row,'numerator')">{{ fmtCell(row.numerator) }}</td>
            <td class="num t-right link" @click="drillDetail(row,'denominator')">{{ fmtCell(row.denominator) }}</td>
            <td class="t-right sep link" @click="drillTrend(row)"><b class="val">{{ fmtValue(row) }}</b></td>
            <td v-for="m in monthCols" :key="row.code+m" class="t-right month-cell" :class="cellLevel(row, m)">
              {{ fmtMonth(row, m) }}
            </td>
            <td class="t-center sep">
              <span class="badge" :class="row.status" :style="statusStyle(row.status)">
                <i class="badge-dot" :style="{ background: statusConfig.meta?.[row.status]?.color }"></i>
                {{ statusText(row.status) }}
              </span>
            </td>
            <td class="t-center"><span class="mini" @click="drillTrend(row)">📈</span></td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 公式悬浮 -->
    <div v-if="tip.show" class="formula-tip" :style="{ left: tip.x+'px', top: tip.y+'px' }">
      <div class="tip-title">{{ tip.data.name }}</div>
      <div v-if="tip.data.mode==='fraction'" class="tip-formula">
        <span class="fraction">
          <span class="numerator">{{ tip.data.numerator }}</span>
          <span class="fraction-line"></span>
          <span class="denominator">{{ tip.data.denominator }}</span>
        </span>
        <span class="multiplier">{{ tip.data.sign }}</span>
      </div>
      <div v-else-if="tip.data.mode==='special'" class="tip-special">
        <div v-for="(l,i) in tip.data.lines" :key="i" class="special-line">{{ l }}</div>
      </div>
      <div v-else class="tip-note">{{ tip.data.note }}</div>
      <div class="tip-meaning">{{ tip.data.meaning }}</div>
    </div>

    <Modal v-if="trendData" :title="`${trendData.name} · ${year}年趋势`" @close="trendData=null"><TrendModal :data="trendData" /></Modal>
    <Modal v-if="detailData" :title="detailTitle" @close="detailData=null">
      <DetailModal :data="detailData" :period="period" :end-period="isMultiMonth ? periodEnd : ''" :unit="unit" :unit-name="deptName" />
    </Modal>
    <Modal v-if="guideVisible" title="指标口径说明" @close="guideVisible=false"><IndicatorGuideModal /></Modal>

    <!-- Toast 通知 -->
    <Transition name="toast-fade">
      <div v-if="toast.show" class="toast" :class="toast.type">{{ toast.message }}</div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue';
import { INDICATORS, evalStatus, getStatusConfig, statusText as getStatusText } from './config/indicators.js';
import Modal from './components/Modal.vue';
import TrendModal from './components/TrendModal.vue';
import DetailModal from './components/DetailModal.vue';
import IndicatorGuideModal from './components/IndicatorGuideModal.vue';
import { fetchDepartments, fetchIndicatorList, fetchTrend as apiFetchTrend, fetchDetail as apiFetchDetail, triggerRefresh as apiTriggerRefresh, getRefreshStatus } from './api/index.js';

const year = ref(2026), startMonth = ref(6), endMonth = ref(6), unit = ref('all');
const years = [2024, 2025, 2026];
const rows = ref([]); const trendData = ref(null); const detailData = ref(null);
const guideVisible = ref(false);
const departments = ref([]); const deptName = ref('全部ICU');
const refreshing = ref(false);
const toast = ref({ show: false, message: '', type: 'success' });
const statusConfig = ref(getStatusConfig());
let _refreshTimer = null;
let _refreshPollTimer = null;
const activeRefreshTask = ref(null);

const monthCols = computed(() => {
  if (startMonth.value === endMonth.value) return [];
  const arr = []; for (let m = startMonth.value; m <= endMonth.value; m++) arr.push(m);
  return arr;
});
const isMultiMonth = computed(() => monthCols.value.length > 0);
const period = computed(() => `${year.value}-${String(startMonth.value).padStart(2,'0')}`);
const periodEnd = computed(() => `${year.value}-${String(endMonth.value).padStart(2,'0')}`);

function fmtMonth(row, m) {
  const v = row.monthly?.[m];
  return v == null ? '/' : `${v}${row.unit}`;
}
function fmtCell(v) { return v == null ? '/' : v; }
function fmtValue(row) { return row.value == null ? '/' : `${row.value}${row.unit}`; }
function displayCode(code) {
  return INDICATORS.find(i => i.code === code)?.displayCode || code;
}
function codeOrder(code) {
  const shown = displayCode(code);
  const match = shown.match(/^ICU-(\d+)(?:-(\d+)h)?$/);
  if (!match) return Number.MAX_SAFE_INTEGER;
  return Number(match[1]) * 100 + Number(match[2] || 0);
}
function cellLevel(row, m) {
  const v = row.monthly?.[m]; if (v == null) return '';
  const base = row.value;
  if (base && Math.abs(v - base) / base > 0.15) return 'alert';
  return '';
}
function statusStyle(status) {
  const meta = statusConfig.value.meta?.[status];
  if (!meta) return {};
  return { color: meta.color, background: meta.background };
}

// 公式悬浮
const tip = ref({ show:false, x:0, y:0, data:null });
function buildFormula(code) {
  const ind = INDICATORS.find(i => i.code === code); if (!ind) return null;
  const base = { name: ind.name, meaning: ind.meaning };
  if (ind.formulaDetail?.type === 'special') return { ...base, mode:'special', lines: ind.formulaDetail.lines };
  if (ind.formulaDetail?.type === 'note') return { ...base, mode:'note', note: ind.formulaDetail.note };
  const sign = ind.multiplier===100?'× 100%':ind.multiplier===1000?'× 1000‰':'';
  return { ...base, mode:'fraction', numerator: ind.numerator, denominator: ind.denominator, sign };
}
function showTip(e, code){ const d=buildFormula(code); if(!d)return; tip.value={show:true,x:e.clientX+16,y:e.clientY+12,data:d}; }
function moveTip(e){ if(tip.value.show){ tip.value.x=e.clientX+16; tip.value.y=e.clientY+12; } }
function hideTip(){ tip.value.show=false; }

// ===== 真实 API 数据加载 =====
async function reload(nocache = false) {
  return reloadRange(period.value, isMultiMonth.value ? periodEnd.value : '', nocache);
}

async function reloadRange(startPeriod, endPeriod = '', nocache = false) {
  try {
    const data = await fetchIndicatorList(startPeriod, unit.value, endPeriod, nocache);
    // 后端返回 monthly 是数组，转换为 {月份: 值} 对象
    rows.value = data.sort((a, b) => codeOrder(a.code) - codeOrder(b.code)).map(r => {
      if (r.months && r.monthly) {
        const map = {};
        r.months.forEach((mon, i) => { map[parseInt(mon.split('-')[1])] = r.monthly[i]; });
        r.monthly = map;
      }
      return r;
    });
    rows.value = rows.value.map(r => {
      const ind = INDICATORS.find(i => i.code === r.code);
      return ind && r.value != null ? { ...r, status: evalStatus(ind, r.value, statusConfig.value) } : r;
    });
  } catch { rows.value = []; }
}

async function drillTrend(row) {
  if (row.value == null) return;
  try { trendData.value = await apiFetchTrend(row.code, year.value, unit.value, startMonth.value, endMonth.value); } catch { /* */ }
}
async function drillDetail(row, part) {
  if (row[part] == null) return;
  const endP = isMultiMonth.value ? periodEnd.value : '';
  const base = { code: row.code, name: row.name, part, count: 0, source_desc: '明细加载中...', patients: [], loading: true };
  detailData.value = base;
  try {
    detailData.value = await apiFetchDetail(row.code, period.value, part, unit.value, endP, { limit: 200, offset: 0 });
  } catch (e) {
    detailData.value = { ...base, loading: false, error: e.message || '明细加载失败', source_desc: '明细加载失败' };
  }
}

const detailTitle = computed(()=> detailData.value
  ? `${detailData.value.name} · ${detailData.value.part==='numerator'?'分子':'分母'}明细` : '');
function showToast(message, type = 'success', duration = 4000) {
  toast.value = { show: true, message, type };
  clearTimeout(_refreshTimer);
  _refreshTimer = setTimeout(() => { toast.value.show = false; }, duration);
}

async function triggerRefresh() {
  if (refreshing.value) {
    if (activeRefreshTask.value) pollRefreshTask(activeRefreshTask.value, true);
    return;
  }  // 防重复点击
  refreshing.value = true;
  const refreshYear = year.value;
  const refreshStartMonth = startMonth.value;
  const refreshEndMonth = endMonth.value;
  const refreshStartPeriod = `${refreshYear}-${String(refreshStartMonth).padStart(2, '0')}`;
  const refreshEndPeriod = `${refreshYear}-${String(refreshEndMonth).padStart(2, '0')}`;

  try {
    const refreshTask = await apiTriggerRefresh(unit.value, refreshYear, refreshStartMonth, refreshEndMonth);
    const task = {
      ...refreshTask,
      refreshYear,
      refreshUnit: unit.value,
      refreshStartPeriod,
      refreshEndPeriod,
      refreshStartMonth,
      refreshEndMonth,
    };

    if (refreshTask.immediate || refreshTask.status === 'completed') {
      activeRefreshTask.value = task;
      await finishRefreshTask(task);
      return;
    }

    activeRefreshTask.value = task;
    const reused = refreshTask.reused ? '已有同范围任务在后台执行' : '已开始后台重算';
    showToast(`${reused} · 已完成 ${refreshTask.done ?? 0}/${refreshTask.total ?? '?'}`, 'info', 5000);
    pollRefreshTask(task, true);
  } catch (e) {
    refreshing.value = false;
    showToast(e.message || '刷新失败', 'error', 6000);
  }
}

async function pollRefreshTask(task, immediate = false) {
  clearTimeout(_refreshPollTimer);
  if (!task?.task_id) {
    refreshing.value = false;
    return;
  }

  const run = async () => {
    try {
      const latest = await getRefreshStatus(task.task_id);
      if (latest.status === 'completed') {
        await finishRefreshTask({ ...task, ...latest });
        return;
      }
      if (latest.status === 'error') {
        refreshing.value = false;
        activeRefreshTask.value = null;
        showToast(latest.error || '刷新失败', 'error', 6000);
        return;
      }
      if (latest.status === 'not_found') {
        refreshing.value = false;
        activeRefreshTask.value = null;
        showToast('后台刷新任务已过期，请重新刷新', 'error', 6000);
        return;
      }

      activeRefreshTask.value = { ...task, ...latest };
      const done = latest.done ?? 0;
      const total = latest.total ?? task.total ?? '?';
      const started = latest.started ? `，已启动 ${latest.started}` : '';
      const current = latest.current_period && latest.current_indicator
        ? `，当前 ${latest.current_period} ${latest.current_indicator}`
        : '';
      showToast(`后台重算中 · ${done}/${total}${started}${current}`, 'info', 5000);
      _refreshPollTimer = setTimeout(() => pollRefreshTask(activeRefreshTask.value), 3000);
    } catch (e) {
      showToast(e.message || '刷新进度获取失败，后台任务仍可能在执行', 'error', 6000);
      _refreshPollTimer = setTimeout(() => pollRefreshTask(activeRefreshTask.value || task), 8000);
    }
  };

  if (immediate) run();
  else _refreshPollTimer = setTimeout(run, 3000);
}

async function finishRefreshTask(task) {
  clearTimeout(_refreshPollTimer);
  const stillOnRefreshRange =
    year.value === task.refreshYear &&
    unit.value === task.refreshUnit &&
    startMonth.value === task.refreshStartMonth &&
    endMonth.value === task.refreshEndMonth;
  if (stillOnRefreshRange) {
    await reloadRange(
      task.refreshStartPeriod ?? period.value,
      (task.refreshStartMonth ?? startMonth.value) === (task.refreshEndMonth ?? endMonth.value)
        ? ''
        : (task.refreshEndPeriod ?? periodEnd.value),
      true,
    );
  }
  refreshing.value = false;
  activeRefreshTask.value = null;
  showToast(
    `预聚合刷新完成 · ${task.stats?.success ?? task.success ?? '?'}/${task.stats?.total ?? task.total ?? '?'} 项成功`,
    'success',
  );
}

function statusText(s){ return getStatusText(s, statusConfig.value); }

function exportCsv() {
  const header = '编码,指标名称,分子,分母,比值,状态\n';
  const body = rows.value.map(r =>
    `${displayCode(r.code)},${r.name},${r.numerator??'/'},${r.denominator??'/'},${r.value == null ? '/' : `${r.value}${r.unit}`},${statusText(r.status)}`).join('\n');
  const blob = new Blob(['﻿'+header+body], { type:'text/csv;charset=utf-8' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
  a.download = `ICU质控_${period.value}.csv`; a.click();
}

// 科室列表 + URL deptCode
async function loadDepartments() {
  try { departments.value = await fetchDepartments(); } catch { departments.value = []; }
  const params = new URLSearchParams(window.location.search);
  const urlCode = params.get('deptCode');
  if (urlCode) {
    const dept = departments.value.find(d => d.code === urlCode);
    if (dept) { unit.value = dept.code; deptName.value = dept.name; return; }
  }
  deptName.value = '全部ICU';
}
watch(unit, (val) => {
  deptName.value = val === 'all' ? '全部ICU' : (departments.value.find(d=>d.code===val)?.name || val);
  const url = new URL(window.location);
  val === 'all' ? url.searchParams.delete('deptCode') : url.searchParams.set('deptCode', val);
  window.history.replaceState({}, '', url);
});

onMounted(async () => { await loadDepartments(); await reload(true); });
window.addEventListener('status-config-updated', () => {
  statusConfig.value = getStatusConfig();
  rows.value = rows.value.map(r => {
    const ind = INDICATORS.find(i => i.code === r.code);
    return ind && r.value != null ? { ...r, status: evalStatus(ind, r.value, statusConfig.value) } : r;
  });
});
</script>

<style scoped>
.table-page { padding: 20px 28px; }
.filter-bar { display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; }
.page-title { font-size:15px; font-weight:600; color:var(--text-main); }
.filters { display:flex; gap:8px; align-items:center; }
.filters select { background:#fff; color:var(--text-main); border:1px solid var(--border);
  border-radius:7px; padding:6px 10px; font-size:13px; cursor:pointer; }
.dash { color:var(--text-faint); }
.refresh-btn { background:#fff; color:var(--brand); border:1px solid var(--brand);
  border-radius:7px; padding:7px 16px; cursor:pointer; font-size:13px; font-weight:500;
  display:inline-flex; align-items:center; gap:6px; transition:all .2s; }
.refresh-btn:hover:not(:disabled) { background:rgba(44,123,229,0.06); }
.refresh-btn:disabled { opacity:.65; cursor:not-allowed; }
.spinner { display:inline-block; width:14px; height:14px; border:2px solid var(--brand);
  border-top-color:transparent; border-radius:50%; animation:spin .7s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
.export-btn { background:var(--brand); color:#fff; border:none; border-radius:7px;
  padding:7px 16px; cursor:pointer; font-size:13px; font-weight:500; }
.guide-btn { background:#f8fafc; color:#1e3a5f; border:1px solid #cbd5e1; border-radius:7px;
  padding:7px 14px; cursor:pointer; font-size:13px; font-weight:500; }
.guide-btn:hover { background:#eff6ff; border-color:#93c5fd; color:#1d4ed8; }

/* Toast 通知 */
.toast { position:fixed; bottom:32px; right:32px; z-index:999;
  padding:12px 22px; border-radius:9px; font-size:14px; font-weight:500;
  box-shadow:0 4px 20px rgba(16,30,54,0.15);
  max-width:420px; line-height:1.5; }
.toast.success { background:#ecfdf5; color:#065f46; border:1px solid #a7f3d0; }
.toast.error { background:#fef2f2; color:#991b1b; border:1px solid #fecaca; }
.toast.info { background:#eff6ff; color:#1e3a5f; border:1px solid #bfdbfe; }
.toast-fade-enter-active { transition:all .3s ease-out; }
.toast-fade-leave-active { transition:all .25s ease-in; }
.toast-fade-enter-from, .toast-fade-leave-to { opacity:0; transform: translateY(12px); }

.table-wrap { max-width:680px; margin:0 auto; background:var(--bg-card);
  border:1px solid var(--border); border-radius:var(--radius); overflow:hidden; box-shadow:var(--shadow-md); }
.table-wrap.multi-month { max-width:100%; margin:0; overflow-x:auto; }

.indi-table { width:100%; table-layout:fixed; border-collapse:separate; border-spacing:0; }
.table-wrap.multi-month .indi-table { width:auto; min-width:100%; }

.c-code{width:72px} .c-name{width:190px} .c-num{width:72px} .c-val{width:82px}
.c-month{width:72px} .c-status{width:64px} .c-trend{width:52px}

.indi-table th, .indi-table td {
  padding:13px 14px; font-size:13px;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}
.indi-table th {
  background:var(--bg-header); color:var(--text-faint);
  font-size:11px; font-weight:600; letter-spacing:0.04em;
  border-bottom:1px solid var(--border);
}
.indi-table td { color:var(--text-main); border-bottom:1px solid var(--border-light); }
.indi-table tbody tr:last-child td { border-bottom:none; }
.indi-table tbody tr:hover td { background:var(--bg-hover); }

.t-left{text-align:left} .t-right{text-align:right} .t-center{text-align:center}

/* 数字专用等宽字体 — Windows 优先 Consolas/Cascadia */
.num, .month-cell, .t-right, .code, .val {
  font-family: 'Cascadia Code', 'Consolas', 'SF Mono', 'JetBrains Mono', ui-monospace, monospace;
  font-variant-numeric:tabular-nums;
}
.sep { border-right:1px solid var(--border); }

.code { color:var(--text-faint); font-size:12px; }
.name-txt { vertical-align:middle; }
/* 分子分母:中性深灰；比值:品牌蓝突出 */
.num { color: var(--text-main); }
.val { color: var(--brand); font-weight:600; }
.link { cursor:pointer; }
.link:hover { color:var(--brand); }

/* 月份列:默认安静灰色,仅异常点亮 */
.month-cell { color: var(--text-sub); font-weight:400; font-size:12px; }
.month-cell.alert { color: var(--warn); font-weight:500; }

.formula-icon { margin-left:5px; font-style:italic; font-size:11px; color:var(--brand);
  background:rgba(59,111,222,0.08); border-radius:3px; padding:0 4px; opacity:.5; }
.name:hover .formula-icon { opacity:1; }

/* 状态徽章:圆点+文字 */
.badge { padding:3px 10px; border-radius:20px; font-size:11px; font-weight:500;
  display:inline-flex; align-items:center; gap:4px; }
.badge-dot { width:5px; height:5px; border-radius:50%; flex-shrink:0; display:inline-block; }
.badge.good { background:rgba(21,150,107,0.08); color:var(--good); }
.badge.good::before { background:var(--good); }
.badge.warn { background:rgba(201,122,22,0.08); color:var(--warn); }
.badge.warn::before { background:var(--warn); }
.badge.danger { background:rgba(207,64,64,0.08); color:var(--danger); }
.badge.danger::before { background:var(--danger); }
.mini { cursor:pointer; opacity:.35; } .mini:hover { opacity:.6; }

.formula-tip { position:fixed; z-index:200; pointer-events:none; background:#fff;
  border:1px solid var(--border); border-radius:9px; box-shadow:var(--shadow-md);
  padding:12px 16px; min-width:230px; max-width:360px; }
.tip-title { font-size:12px; font-weight:600; color:var(--text-main); margin-bottom:10px; }
.tip-formula { display:flex; align-items:center; gap:8px; margin-bottom:8px; }
.fraction { display:inline-flex; flex-direction:column; text-align:center; }
.numerator, .denominator { padding:2px 8px; font-size:12px; white-space:nowrap; }
.fraction-line { height:1px; background:var(--text-main); }
.multiplier { font-size:12px; color:var(--brand); }
.tip-special .special-line { font-size:12px; line-height:1.8; color:var(--text-main); }
.tip-note { font-size:12px; line-height:1.6; color:var(--text-main); margin-bottom:8px; }
.tip-meaning { font-size:11px; color:var(--text-sub); padding-top:8px; border-top:1px dashed var(--border); }
</style>
