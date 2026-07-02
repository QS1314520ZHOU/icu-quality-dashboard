<template>
  <div>
    <div class="source">
      <span class="tag">数据源</span>{{ data.source_desc }}
      <span class="count" v-if="data.count > 0">
        共 {{ data.count }} 例<span v-if="data.has_more">，先显示 {{ data.patients?.length || 0 }} 例</span>
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
    <!-- 通用表格（共享列定义） -->
    <table v-else class="detail-table">
      <thead>
        <tr><th v-for="c in columns" :key="c.header">{{ c.header }}</th></tr>
      </thead>
      <tbody>
        <tr v-for="p in data.patients" :key="p.detail_id || p.patient_id" :class="rowClass(p)"
            :title="p.admission_source === 'low_confidence' ? '⚠️ AI判定置信度<0.6，待人工复核' : ''">
          <td v-for="c in columns" :key="c.header" :class="{ mono: c.header === '住院号' || c.header === '账号' }">
            {{ c.get(p) }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
<script setup>
import { computed, ref } from 'vue';
import { getDetailColumns } from '../utils/detailColumns.js';
import { exportDetailExcel } from '../utils/exportExcel.js';

const props = defineProps({
  data: Object,
  period: { type: String, default: '' },
  endPeriod: { type: String, default: '' },
  unit: { type: String, default: 'all' },
  unitName: { type: String, default: '' },
});

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
.source { font-size:13px; color:#475569; margin-bottom:14px; padding:10px 12px;
  background:#f0f6ff; border-radius:6px; border: 1px solid rgba(0,82,217,0.08); }
.tag { background:#0052d9; color:#fff; padding:1px 8px; border-radius:4px; font-size:11px; margin-right:8px; }
.count { float:right; color:#0052d9; font-weight:600; }
.export-btn { float:right; margin-left:10px; padding:3px 12px; font-size:12px;
  background:#0052d9; color:#fff; border:none; border-radius:4px; cursor:pointer;
  line-height:1.8; }
.export-btn:hover:not(:disabled) { background:#003db3; }
.export-btn:disabled { background:#94a3b8; cursor:not-allowed; }
.export-progress { float:right; color:#64748b; font-size:12px; margin-left:8px; }
.export-error { float:right; color:#dc2626; font-size:12px; margin-left:8px; }
.den-summary { font-size:16px; font-weight:600; color:#1e293b; text-align:center;
  padding:32px 20px; background:#f8fafc; border-radius:8px;
  border: 1px solid var(--border); }
.loading, .empty { font-size:14px; color:#64748b; text-align:center; padding:34px 20px;
  background:#f8fafc; border:1px solid var(--border); border-radius:8px; }
.detail-table { width:100%; border-collapse:collapse; }
.detail-table th { color:#475569; font-size:12px; padding:8px 10px; text-align:left;
  border-bottom:1px solid rgba(0,0,0,0.08); font-weight:600; }
.detail-table td { padding:9px 10px; font-size:13px; color:#334155;
  border-bottom:1px solid rgba(0,0,0,0.05); }
.mono { font-family:monospace; color:#64748b; }
.tri-list { display:flex; flex-direction:column; gap:10px; }
.tri-card { border:1px solid #e2e8f0; border-radius:8px; background:#fff; padding:12px 14px; }
.tri-card:hover { border-color:#bfdbfe; background:#f8fbff; }
.tri-head { display:flex; justify-content:space-between; gap:14px; align-items:flex-start; }
.tri-person { display:flex; gap:10px; align-items:center; min-width:180px; }
.tri-person strong { color:#0f172a; font-size:14px; }
.tri-metrics { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:6px; }
.tri-metrics span { background:#eff6ff; border:1px solid #dbeafe; color:#1d4ed8;
  border-radius:6px; padding:3px 8px; font-size:12px; font-weight:600; }
.tri-basis { margin:8px 0 0; color:#334155; font-size:13px; line-height:1.65; }
/* ICU-06 低置信度行：黄色背景 + 左侧警告条 */
tr.low-confidence { background: #fff8e1; }
tr.low-confidence:hover td { background: #ffecb3; }
tr.low-confidence td:first-child::before {
  content: '⚠️'; margin-right: 4px; font-size: 12px;
}
</style>
