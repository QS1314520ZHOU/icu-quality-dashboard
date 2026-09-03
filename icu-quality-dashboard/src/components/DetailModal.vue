<template>
  <div>
    <div class="source">
      <span class="tag">数据源</span>{{ data.source_desc }}
      <span class="count" v-if="data.count > 0">
        共 {{ data.count }} 例<span v-if="data.has_more">，先显示 {{ data.patients?.length || 0 }} 例</span>
      </span>
      <span v-if="canExclude && excludedCount > 0" class="excl-count">
        ，已人工排除 {{ excludedCount }} 例
      </span>
      <button class="export-btn" :disabled="exporting || !data.patients?.length || isSummary"
              @click="handleExport" :title="isSummary ? '汇总数据无需导出' : !data.patients?.length ? '无可导出数据' : ''">
        {{ exporting ? '导出中...' : '导出 Excel' }}
      </button>
      <span v-if="exportProgress" class="export-progress">{{ exportProgress }}</span>
      <span v-if="exportError" class="export-error">{{ exportError }}</span>
    </div>
    <div v-if="data.loading" class="loading">明细加载中...</div>
    <div v-else-if="data.error" class="empty">{{ data.error }}</div>
    <div v-else-if="!data.patients?.length" class="empty">暂无明细</div>
    <!-- 分母汇总 -->
    <div v-else-if="isSummary" class="den-summary">{{ data.patients[0].name }}</div>
    <!-- 三管卡片布局（ICU-16/17/CAUTI） -->
    <div v-else-if="isTriTube" class="tri-list">
      <article v-for="p in data.patients" :key="p.detail_id || p.patient_id" class="tri-card">
        <div class="tri-head">
          <div class="tri-person">
            <span class="mono">{{ p.patient_id }}</span>
            <strong>{{ p.name || '—' }}</strong>
          </div>
          <div class="tri-metrics">
            <span v-for="c in columns.slice(2)" :key="c.header">{{ c.get(p) }}</span>
          </div>
        </div>
        <p class="tri-basis">{{ columns[columns.length - 1]?.get(p) }}</p>
      </article>
    </div>
    <!-- ICU-00 患者类型筛选 -->
    <div v-if="hasPatientType && data.patients?.length" class="census-filter">
      <span class="filter-label">筛选：</span>
      <button :class="['filter-btn', { active: !patientTypeFilter }]" @click="patientTypeFilter = ''">全部</button>
      <button :class="['filter-btn', { active: patientTypeFilter === '原有' }]" @click="patientTypeFilter = '原有'">原有</button>
      <button :class="['filter-btn', { active: patientTypeFilter === '新入' }]" @click="patientTypeFilter = '新入'">新入</button>
      <button :class="['filter-btn', { active: patientTypeFilter === '出科' }]" @click="patientTypeFilter = '出科'">出科</button>
      <span class="filter-count">共 {{ filteredPatients.length }} 例</span>
    </div>
    <!-- 通用表格（共享列定义） -->
    <table v-if="data.patients?.length && !isSummary && !isTriTube" class="detail-table">
      <thead>
        <tr><th v-for="c in columns" :key="c.header">{{ c.header }}</th><th v-if="canExclude">操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="p in filteredPatients" :key="p.detail_id || p.patient_id" :class="[rowClass(p), p.excluded ? 'excluded-row' : '']"
            :title="p.admission_source === 'low_confidence' ? 'AI判定置信度<0.6，待人工复核' : ''">
          <td v-for="c in columns" :key="c.header" :class="{ mono: c.header === '住院号' || c.header === '账号' }">
            {{ c.get(p) }}
          </td>
          <td v-if="canExclude" class="action-cell">
            <template v-if="p.excluded">
              <button class="btn-restore" @click="handleRestore(p)">恢复</button>
              <span class="reason-tag">{{ getReasonLabel(p.reason_code) }}</span>
            </template>
            <template v-else>
              <button class="btn-exclude" @click="handleExclude(p)">排除</button>
            </template>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
    <!-- 排除原因弹窗 -->
    <Teleport to="body">
      <div v-if="showExclForm" class="excl-overlay" @click.self="showExclForm=false">
        <div class="excl-dialog">
          <h3>排除患者</h3>
          <div class="excl-field">
            <label>患者：{{ exclForm.name }} ({{ exclForm.patient_id }})</label>
          </div>
          <div class="excl-field">
            <label>排除原因 <span class="required">*</span></label>
            <select v-model="exclForm.reason_code">
              <option value="">请选择</option>
              <option v-for="r in EXCL_REASONS" :key="r.code" :value="r.code">{{ r.label }}</option>
            </select>
          </div>
          <div v-if="exclForm.reason_code === 'other'" class="excl-field">
            <label>补充说明 <span class="required">*</span></label>
            <textarea v-model="exclForm.reason_text" rows="2" placeholder="请填写排除说明"></textarea>
          </div>
          <div class="excl-field">
            <label>操作人</label>
            <input v-model="exclForm.operator" placeholder="姓名或工号" />
          </div>
          <div class="excl-actions">
            <button class="btn-cancel" @click="showExclForm=false">取消</button>
            <button class="btn-confirm" @click="submitExclusion" :disabled="!exclForm.reason_code || (exclForm.reason_code==='other' && !exclForm.reason_text.trim())">确认排除</button>
          </div>
        </div>
      </div>
    </Teleport>
</template>
<script setup>
import { computed, ref } from 'vue';
import { getDetailColumns } from '../utils/detailColumns.js';
import { exportDetailExcel } from '../utils/exportExcel.js';
import { addExclusion, removeExclusion } from '../api/index.js';

const props = defineProps({
  data: Object,
  period: { type: String, default: '' },
  endPeriod: { type: String, default: '' },
  unit: { type: String, default: 'all' },
  unitName: { type: String, default: '' },
});

const emit = defineEmits(['exclusion-changed']);

// ---- 人工排除 ----
const showExclForm = ref(false);
const exclForm = ref({ exclusion_key: '', patient_id: '', name: '', reason_code: '', reason_text: '', operator: '' });
const EXCL_REASONS = [
  { code: 'non_ards', label: '非ARDS原因低氧' },
  { code: 'unstable_gas', label: '氧合数据非稳定状态' },
  { code: 'contraindic', label: '存在俯卧位禁忌症' },
  { code: 'terminal', label: '终末期或家属放弃积极治疗' },
  { code: 'data_error', label: 'PEEP或氧疗途径记录错误' },
  { code: 'other', label: '其他' },
];
const EXCLUSION_SUPPORTED_CODES = ['ICU-08'];
const canExclude = computed(() => EXCLUSION_SUPPORTED_CODES.includes(props.data?.code));
const excludedCount = computed(() => (props.data?.patients || []).filter(p => p.excluded).length);
const patientTypeFilter = ref('');
const hasPatientType = computed(() => ['ICU-00','ICU-04','ICU-07','ICU-09','ICU-10'].includes(props.data?.code) && props.data?.part === 'denominator');
const filteredPatients = computed(() => {
  const list = props.data?.patients || [];
  if (!hasPatientType.value || !patientTypeFilter.value) return list;
  return list.filter(p => p.patient_type === patientTypeFilter.value);
});

function getReasonLabel(code) {
  return EXCL_REASONS.find(r => r.code === code)?.label || code;
}

function handleExclude(p) {
  exclForm.value = {
    exclusion_key: p.exclusion_key || '',
    patient_id: p.patient_id || '',
    name: p.name || '',
    reason_code: '',
    reason_text: '',
    operator: '',
  };
  showExclForm.value = true;
}

async function submitExclusion() {
  if (!exclForm.value.reason_code) return;
  if (exclForm.value.reason_code === 'other' && !exclForm.value.reason_text.trim()) return;
  try {
    await addExclusion(props.data.code, {
      period: props.period,
      icu_unit: props.unit,
      ...exclForm.value,
    });
    showExclForm.value = false;
    emit('exclusion-changed');
  } catch (e) {
    console.error('Exclude failed:', e);
  }
}

async function handleRestore(p) {
  try {
    await removeExclusion(props.data.code, p.exclusion_key, props.period, props.unit);
    emit('exclusion-changed');
  } catch (e) {
    console.error('Restore failed:', e);
  }
}

// ── 共享列定义 ──
const columns = computed(() => getDetailColumns(props.data?.code, props.data?.part));

// ── 导出逻辑 ──
const exporting = ref(false);
const exportError = ref('');
const exportProgress = ref('');

async function handleExport() {
  if (exporting.value || !props.data?.patients?.length || isSummary.value) return;
  exporting.value = true;
  exportError.value = '';
  exportProgress.value = '';
  try {
    const { rows, filename, truncated } = await exportDetailExcel({
      code: props.data.code,
      name: props.data.name,
      part: props.data.part,
      period: props.period,
      endPeriod: props.endPeriod,
      unit: props.unit,
      unitName: props.unitName,
      sourceDesc: props.data.source_desc,
      patients: props.data.patients,
      hasMore: props.data.has_more,
      onProgress: (loaded) => { exportProgress.value = `已加载 ${loaded} 条...`; },
    });
    exportProgress.value = '';
    if (truncated) {
      exportError.value = `数据超上限，仅导出前 ${rows} 条`;
    }
    console.log(`[export] 导出完成: ${filename}, ${rows} 行${truncated ? ' (截断)' : ''}`);
  } catch (e) {
    exportProgress.value = '';
    exportError.value = e.message || '导出失败';
    console.error('[export]', e);
  } finally {
    exporting.value = false;
  }
}

// ── 辅助判断 ──
const isSummary = computed(() =>
  props.data?.part === 'denominator' &&
  props.data?.patients?.length === 1 &&
  props.data?.patients[0]?.patient_id === '—'
);
const isTriTube = computed(() => ['ICU-16', 'ICU-17', 'CAUTI'].includes(props.data?.code));

// ICU-06 分母：低置信度 AI 判定行 → 标黄提示人工复核
const rowClass = (p) => {
  if (props.data?.code === 'ICU-06' && props.data?.part === 'denominator'
      && p.admission_source === 'low_confidence') {
    return 'low-confidence';
  }
  return '';
};
</script>
<style scoped>
.source { font-size:var(--fs-label); color:var(--text-sub); margin-bottom:14px; padding:10px 12px;
  background:var(--brand-weak); border-radius:6px; border:1px solid rgba(30,94,184,0.08); }
.tag { background:var(--brand); color:#fff; padding:1px 8px; border-radius:4px; font-size:var(--fs-caption); margin-right:8px; }
.count { float:right; color:var(--brand); font-weight:600; }
.export-btn { float:right; margin-left:10px; padding:3px 12px; font-size:var(--fs-caption);
  background:var(--brand); color:#fff; border:none; border-radius:4px; cursor:pointer;
  line-height:1.8; }
.export-btn:hover:not(:disabled) { background:var(--brand); opacity:.85; }
.export-btn:disabled { background:var(--text-faint); cursor:not-allowed; }
.export-progress { float:right; color:var(--text-sub); font-size:var(--fs-caption); margin-left:8px; }
.export-error { float:right; color:var(--danger); font-size:var(--fs-caption); margin-left:8px; }
.den-summary { font-size:16px; font-weight:600; color:var(--text-title); text-align:center;
  padding:32px 20px; background:#f8fafc; border-radius:8px;
  border: 1px solid var(--border); }
.loading, .empty { font-size:var(--fs-body); color:var(--text-sub); text-align:center; padding:34px 20px;
  background:var(--bg-subtle); border:1px solid var(--border); border-radius:8px; }
.detail-table { width:100%; border-collapse:collapse; }
.detail-table th { color:var(--text-sub); font-size:var(--fs-caption); padding:8px 10px; text-align:left;
  border-bottom:1px solid var(--border); font-weight:600; }
.detail-table td { padding:9px 10px; font-size:var(--fs-label); color:var(--text-body);
  border-bottom:1px solid var(--border-light); }
.mono { font-family:monospace; color:var(--text-sub); }
.tri-list { display:flex; flex-direction:column; gap:10px; }
.tri-card:hover { border-color:var(--border-strong); background:var(--bg-hover); }
.tri-card { border:1px solid var(--border); border-radius:8px; background:var(--bg-surface); padding:12px 14px; }
.tri-card:hover { border-color:#bfdbfe; background:#f8fbff; }
.tri-head { display:flex; justify-content:space-between; gap:14px; align-items:flex-start; }
.tri-person { display:flex; gap:10px; align-items:center; min-width:180px; }
.tri-person strong { color:var(--text-title); font-size:var(--fs-body); }
.tri-metrics { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:6px; }
.tri-metrics span { background:var(--brand-weak); border:1px solid rgba(30,94,184,0.15); color:var(--brand);
  border-radius:6px; padding:3px 8px; font-size:var(--fs-caption); font-weight:600; }
.tri-basis { margin:8px 0 0; color:var(--text-body); font-size:var(--fs-label); line-height:1.65; }
/* ICU-06 低置信度行：黄色背景 + 左侧警告条 */
tr.low-confidence { background: var(--warn-weak); }
tr.low-confidence:hover td { background: rgba(178,106,0,0.12); }
tr.low-confidence td:first-child::before {
  content: ''; display: inline-block; width: 12px; height: 12px; margin-right: 4px;
  background: var(--warn); border-radius: 50%; vertical-align: -1px;
}

/* Exclusion styles */
.action-cell { text-align: center; white-space: normal; }
.btn-exclude { background: var(--warn); color: #fff; border: none; border-radius: 4px; padding: 3px 10px; font-size: var(--fs-caption); cursor: pointer; }
.btn-exclude:hover { opacity:.85; }
.btn-restore { background: var(--brand); color: #fff; border: none; border-radius: 4px; padding: 3px 10px; font-size: var(--fs-caption); cursor: pointer; }
.btn-restore:hover { opacity:.85; }
.reason-tag { display: inline-block; margin-left: 4px; font-size: var(--fs-caption); color: var(--text-sub); background: var(--bg-subtle); border-radius: 3px; padding: 1px 6px; }
.excl-count { color: var(--warn); font-weight: 600; }
tr.excluded-row { opacity: 0.5; }
tr.excluded-row td { text-decoration: line-through; }
.excl-overlay { position: fixed; inset: 0; z-index: 9999; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; }
.excl-dialog { background: var(--bg-surface); border-radius: 12px; padding: 24px; width: 420px; max-width: 90vw; box-shadow: var(--shadow-card); }
.excl-dialog h3 { margin: 0 0 16px; font-size: 16px; color: var(--text-title); }
.excl-field { margin-bottom: 12px; }
.excl-field label { display: block; font-size: var(--fs-label); color: var(--text-sub); margin-bottom: 4px; font-weight: 500; }
.excl-field .required { color: var(--danger); }
.excl-field select, .excl-field input, .excl-field textarea {
  width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: var(--fs-label); }
.excl-field textarea { resize: vertical; }
.excl-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
.btn-cancel { padding: 7px 16px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-surface); font-size: var(--fs-label); cursor: pointer; }
.btn-confirm { padding: 7px 16px; border: none; border-radius: 6px; background: var(--danger); color: #fff; font-size: var(--fs-label); cursor: pointer; }
.btn-confirm:disabled { opacity: 0.5; cursor: not-allowed; }
.census-filter { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; padding: 8px 12px; background: var(--bg-subtle); border: 1px solid var(--border); border-radius: 6px; }
.filter-label { font-size: var(--fs-caption); color: var(--text-sub); font-weight: 600; }
.filter-btn { padding: 4px 12px; border: 1px solid var(--border); border-radius: 4px; background: var(--bg-surface); font-size: var(--fs-caption); cursor: pointer; color: var(--text-sub); }
.filter-btn:hover { border-color: var(--brand); color: var(--brand); }
.filter-btn.active { background: var(--brand); color: #fff; border-color: var(--brand); }
.filter-count { margin-left: auto; font-size: var(--fs-caption); color: var(--text-sub); }
</style>
