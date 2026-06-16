<template>
  <div class="ai-panel">
    <div class="ai-section">
      <div class="ai-head">AI 总结</div>
      <div class="ai-summary">
        <strong>{{ attentionText }}</strong>
        <p>{{ analysis?.summary || '暂无 AI 分析结果' }}</p>
      </div>
      <div class="ai-explain">{{ analysis?.explain || 'AI待办为质控复核线索，不代表已确诊事件。' }}</div>
    </div>

    <div class="ai-section">
      <div class="section-title">风险线索</div>
      <div v-if="hints.length" class="hint-list">
        <div v-for="h in hints" :key="`${h.trigger}-${h.related}`" class="hint-item">
          <span class="hint-code">{{ h.trigger }}</span>
          <span>{{ h.hint }}</span>
        </div>
      </div>
      <div v-else class="empty">暂无明确关联线索</div>
    </div>

    <div class="ai-section">
      <div class="section-title">待办事项</div>
      <div v-if="todos.length" class="todo-list">
        <div v-for="t in todos" :key="t.type" class="todo-item">
          <div class="todo-main">
            <div class="todo-title">{{ t.title }}</div>
            <div class="todo-desc">{{ t.description }}</div>
            <div class="todo-note">{{ todoExplain(t.type) }}</div>
            <button class="detail-toggle" @click="toggle(t.type)">
              {{ openType === t.type ? '收起明细' : detailButtonText(t.type) }}
            </button>
          </div>
          <span class="todo-count">{{ t.count }}<small>{{ todoUnit(t.type) }}</small></span>
          <div v-if="openType === t.type" class="todo-detail">
            <template v-if="t.type === 'tri_tube_warning'">
              <div v-if="typeSummary.length" class="type-summary">
                <span v-for="x in typeSummary" :key="x.name">{{ x.name }} {{ x.count }}条</span>
              </div>
              <div v-if="triItems.length" class="detail-list">
                <div v-for="item in triItems" :key="`${item.patient_id}-${item.type}-${item.time}`" class="detail-row">
                  <div class="detail-row-head">
                    <strong>{{ item.type }}</strong>
                    <span v-if="item.confidence !== undefined" class="confidence-badge">置信度 {{ confidenceText(item.confidence) }}</span>
                  </div>
                  <span>{{ item.patient_id || '未知患者' }} {{ item.name || '' }}</span>
                  <em>{{ item.basis }}</em>
                  <div class="rule-text">{{ item.rule || '生成条件：装置留置超过阈值，并同时出现感染相关证据；该线索需要人工确认。' }}</div>
                  <div v-if="item.evidence?.length" class="evidence-box">
                    <div class="evidence-title">判断条件</div>
                    <div class="evidence-list">
                      <span v-for="(ev, idx) in item.evidence" :key="`${item.patient_id}-${item.type}-${idx}`">
                        <b>{{ ev.type || '证据' }}</b>
                        <template v-if="ev.value">：{{ ev.value }}</template>
                        <small v-if="ev.time">{{ ev.time }}</small>
                      </span>
                    </div>
                  </div>
                </div>
              </div>
              <div v-else class="empty inner">暂无可展示的线索明细</div>
            </template>
            <template v-else-if="t.type === 'sepsis_alert'">
              <div v-if="sepsisItems.length" class="detail-list">
                <div v-for="item in sepsisItems" :key="`${item.patient_id}-${item.risk}-${item.qsofa}`" class="detail-row">
                  <div class="detail-row-head">
                    <strong>{{ item.type }}</strong>
                    <span class="confidence-badge">{{ riskText(item.risk) }} · qSOFA {{ item.qsofa ?? 0 }}</span>
                  </div>
                  <span>{{ item.patient_id || '未知患者' }} {{ item.name || '' }}</span>
                  <em>{{ item.basis }}</em>
                  <div class="rule-text">{{ item.rule }}</div>
                  <div v-if="item.action" class="action-text">{{ item.action }}</div>
                  <div v-if="item.evidence?.length" class="evidence-box">
                    <div class="evidence-title">判断条件</div>
                    <div class="evidence-list">
                      <span v-for="(ev, idx) in item.evidence" :key="`${item.patient_id}-sepsis-${idx}`">
                        <b>{{ ev.type || '证据' }}</b>
                        <template v-if="ev.value">：{{ ev.value }}</template>
                      </span>
                    </div>
                  </div>
                </div>
              </div>
              <div v-else class="empty inner">暂无可展示的预警明细</div>
            </template>
            <template v-else-if="t.type === 'low_confidence_abx'">
              <div v-if="lowItems.length" class="detail-list">
                <div v-for="item in lowItems" :key="item.hisPid" class="detail-row">
                  <strong>{{ item.hisPid }}</strong>
                  <span>{{ item.purpose || '待判定' }} · 置信度 {{ confidenceText(item.confidence) }}</span>
                  <em>{{ item.reason || '需要人工复核用药目的' }}</em>
                </div>
              </div>
              <div v-else class="empty inner">暂无低置信度记录明细</div>
            </template>
            <div class="detail-foot">这里只展示前几条线索，完整清单请到对应复核页面或明细下钻中查看。</div>
          </div>
        </div>
      </div>
      <div v-else class="empty">暂无 AI 待办</div>
    </div>

    <div class="ai-note">AI 仅辅助质控分析，不替代临床诊疗判断。</div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue';

const props = defineProps({ analysis: Object });
const openType = ref('');
const hints = computed(() => props.analysis?.hints || []);
const todos = computed(() => props.analysis?.todos || []);
const triItems = computed(() => props.analysis?.tri_tube?.items || []);
const sepsisItems = computed(() => props.analysis?.sepsis_alert?.items || []);
const lowItems = computed(() => props.analysis?.low_confidence?.items || []);
const typeSummary = computed(() => Object.entries(props.analysis?.tri_tube?.types || {})
  .map(([name, count]) => ({ name, count })));
const attentionText = computed(() => {
  const abnormal = props.analysis?.abnormal || [];
  const danger = abnormal.filter(i => i.level === 'danger').length;
  const warn = abnormal.filter(i => i.level === 'warn').length;
  return `AI按同一阈值口径识别：${danger}项严重异常，${warn}项预警。`;
});

function todoUnit(type) {
  if (type === 'tri_tube_warning') return '条线索';
  if (type === 'sepsis_alert') return '条预警';
  if (type === 'low_confidence_abx') return '条记录';
  return '项';
}
function todoExplain(type) {
  if (type === 'tri_tube_warning') return '该数字是系统发现的疑似 VAP/CRBSI/CAUTI 线索数：必须同时有装置留置超过 48 小时和感染相关证据，需人工确认后才可能进入正式指标。';
  if (type === 'sepsis_alert') return '该数字是 Sepsis-3 / qSOFA 辅助识别的质控分诊提示，只表示建议临床团队评估，不代表诊断结论。';
  if (type === 'low_confidence_abx') return '该数字是抗菌药用药目的判断信心不足的记录数，需要复核是否纳入 ICU-06 分母。';
  return '该数字表示需要质控人员进一步核查的事项数量。';
}
function detailButtonText(type) {
  if (type === 'tri_tube_warning') return '查看判断条件';
  if (type === 'sepsis_alert') return '查看预警依据';
  return '查看前几条';
}
function toggle(type) {
  openType.value = openType.value === type ? '' : type;
}
function confidenceText(v) {
  const n = Number(v);
  return Number.isNaN(n) ? '/' : n.toFixed(2);
}
function riskText(v) {
  if (v === 'high') return '高危';
  if (v === 'medium') return '中危';
  return '低危';
}
</script>

<style scoped>
.ai-panel { display:flex; flex-direction:column; gap:12px; height:100%; }
.ai-head { font-size:15px; color:#0f5cc0; font-weight:700; }
.ai-section { min-width:0; }
.section-title { font-size:13px; color:#334155; font-weight:700; margin-bottom:8px; }
.ai-summary { font-size:13px; line-height:1.7; color:#243447; background:#f0f6ff;
  border:1px solid #d9e9ff; border-radius:8px; padding:12px; }
.ai-summary strong { display:block; color:#1d4ed8; margin-bottom:5px; }
.ai-summary p { margin:0; }
.ai-explain { margin-top:8px; font-size:12px; line-height:1.55; color:#64748b; }
.hint-list, .todo-list { display:flex; flex-direction:column; gap:8px; }
.hint-item { display:flex; gap:8px; align-items:flex-start; font-size:12px; line-height:1.5;
  color:#475569; background:#fff7ed; border:1px solid #fed7aa; border-radius:8px; padding:9px 10px; }
.hint-code { flex-shrink:0; color:#c2410c; font-weight:700; }
.todo-item { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:12px; align-items:start;
  background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:10px 12px; }
.todo-main { min-width:0; }
.todo-title { color:#1e293b; font-size:13px; font-weight:700; }
.todo-desc { color:#64748b; font-size:12px; margin-top:2px; line-height:1.4; }
.todo-note { color:#475569; font-size:12px; margin-top:5px; line-height:1.45; }
.todo-count { min-width:66px; text-align:center; border-radius:8px; padding:6px 8px;
  color:#b91c1c; background:#fee2e2; border:1px solid #fecaca; font-weight:800; font-size:17px; }
.todo-count small { display:block; font-size:10px; font-weight:600; margin-top:1px; }
.detail-toggle { margin-top:8px; background:#fff; color:#1d4ed8; border:1px solid #bfdbfe;
  border-radius:6px; padding:5px 9px; font-size:12px; cursor:pointer; }
.detail-toggle:hover { background:#eff6ff; }
.todo-detail { grid-column:1 / -1; border-top:1px dashed #cbd5e1; padding-top:9px; margin-top:2px; }
.type-summary { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:8px; }
.type-summary span { background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe; border-radius:999px;
  padding:3px 8px; font-size:12px; }
.detail-list { display:flex; flex-direction:column; gap:6px; }
.detail-row { background:#fff; border:1px solid #e2e8f0; border-radius:7px; padding:8px 9px; }
.detail-row-head { display:flex; align-items:center; gap:8px; justify-content:space-between; margin-bottom:2px; }
.detail-row strong { display:block; color:#0f172a; font-size:12px; }
.confidence-badge { flex-shrink:0; color:#0f766e; background:#ccfbf1; border:1px solid #99f6e4;
  border-radius:999px; padding:2px 7px; font-size:11px; font-weight:700; }
.detail-row span { display:block; color:#475569; font-size:12px; }
.detail-row em { display:block; color:#64748b; font-style:normal; font-size:12px; line-height:1.45; margin-top:3px; }
.rule-text { margin-top:6px; color:#334155; background:#f8fafc; border-left:3px solid #60a5fa;
  padding:6px 8px; font-size:12px; line-height:1.5; }
.action-text { margin-top:6px; color:#0f766e; background:#ecfdf5; border:1px solid #bbf7d0;
  border-radius:6px; padding:5px 8px; font-size:12px; line-height:1.45; }
.evidence-box { margin-top:7px; }
.evidence-title { color:#1e293b; font-size:12px; font-weight:700; margin-bottom:5px; }
.evidence-list { display:flex; flex-wrap:wrap; gap:6px; }
.evidence-list span { display:inline-flex; align-items:center; gap:3px; max-width:100%;
  color:#334155; background:#f1f5f9; border:1px solid #dbe3ef; border-radius:999px;
  padding:4px 8px; line-height:1.35; }
.evidence-list b { color:#0f172a; font-weight:700; }
.evidence-list small { color:#64748b; font-size:11px; margin-left:2px; }
.detail-foot { color:#64748b; font-size:12px; margin-top:8px; line-height:1.5; }
.empty { color:#94a3b8; font-size:12px; background:#f8fafc; border:1px dashed #cbd5e1;
  border-radius:8px; padding:10px 12px; }
.empty.inner { background:#fff; }
.ai-note { margin-top:auto; padding-top:10px; color:#64748b; font-size:11px;
  border-top:1px dashed #cbd5e1; }
</style>
