<template>
  <div>
    <div class="source">
      <span class="tag">数据源</span>{{ data.source_desc }}
      <span class="count" v-if="data.count > 0">共 {{ data.count }} 例</span>
    </div>
    <!-- 分母汇总 -->
    <div v-if="isSummary" class="den-summary">{{ data.patients[0].name }}</div>
    <!-- 表格 -->
    <table v-else class="detail-table">
      <thead>
        <tr>
          <th>{{ col1 }}</th><th>姓名</th><th>{{ col3 }}</th><th>{{ col4 }}</th><th>{{ col5 }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="p in data.patients" :key="p.patient_id" :class="rowClass(p)"
            :title="p.admission_source === 'low_confidence' ? '⚠️ AI判定置信度<0.6，待人工复核' : ''">
          <td class="mono">{{ p.patient_id }}</td>
          <td>{{ p.name }}</td>
          <td>{{ p.bed_no }}</td>
          <td>{{ p.admit_time }}</td>
          <td>{{ p.value ?? '—' }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
<script setup>
import { computed } from 'vue';
const props = defineProps({ data: Object });

const isStaff = computed(() => ['ICU-02','ICU-03'].includes(props.data?.code));
const isSummary = computed(() =>
  props.data?.part === 'denominator' &&
  props.data?.patients?.length === 1 &&
  props.data?.patients[0]?.patient_id === '—'
);
const isICU06 = computed(() => props.data?.code === 'ICU-06');
const isICU07 = computed(() => props.data?.code === 'ICU-07');
const isICU08 = computed(() => props.data?.code === 'ICU-08');
const isICU09 = computed(() => props.data?.code === 'ICU-09');
const isICU10 = computed(() => props.data?.code === 'ICU-10');
const col1 = computed(() => isStaff.value ? '账号' : '住院号');
const col3 = computed(() => {
  if (isStaff.value) return '职称';
  if (isICU08.value && props.data?.part === 'denominator') return 'P/F  PEEP';
  if (isICU08.value && props.data?.part === 'numerator') return '俯卧次数';
  if (isICU06.value && props.data?.part === 'denominator') return '抗菌药 [目的]';
  if (isICU06.value && props.data?.part === 'numerator') return '送检项目';
  if (isICU07.value && props.data?.part === 'numerator') return '预防措施';
  if (isICU09.value && props.data?.part === 'numerator') return '评估来源';
  if (isICU10.value && props.data?.part === 'numerator') return '评估来源';
  return '床号';
});
const col4 = computed(() => {
  if (isStaff.value) return '入职日期';
  if (isICU08.value && props.data?.part === 'denominator') return '纳入路径';
  if (isICU08.value && props.data?.part === 'numerator') return '首次俯卧时间';
  if (isICU06.value && props.data?.part === 'denominator') return '给药 & 判定理由';
  if (isICU06.value && props.data?.part === 'numerator') return '送检时间';
  if (isICU07.value && props.data?.part === 'numerator') return '医嘱示例';
  if (isICU09.value && props.data?.part === 'numerator') return '评估量表';
  if (isICU10.value && props.data?.part === 'numerator') return '评估值';
  return '入科时间';
});
const col5 = computed(() => {
  if (isStaff.value) return '人数';
  if (isICU08.value && props.data?.part === 'denominator') return 'P/F值';
  if (isICU08.value && props.data?.part === 'numerator') return '俯卧总次数';
  if (props.data?.code === 'ICU-04' && props.data?.part === 'numerator') return 'APACHEⅡ';
  if (props.data?.code === 'ICU-04' && props.data?.part === 'denominator') return '在科';
  if (props.data?.part === 'numerator' && props.data?.code === 'ICU-01') return '在床天数';
  if (isICU06.value && props.data?.part === 'denominator') return '给药次数';
  if (isICU07.value && props.data?.part === 'numerator') return '医嘱条数';
  if (isICU09.value && props.data?.part === 'numerator') return '评估时间';
  if (isICU10.value && props.data?.part === 'numerator') return '评估时间';
  return '数值';
});
// ICU-06 分母：低置信度 AI 判定行 → 标黄提示人工复核
const rowClass = (p) => {
  if (isICU06.value && props.data?.part === 'denominator'
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
.den-summary { font-size:16px; font-weight:600; color:#1e293b; text-align:center;
  padding:32px 20px; background:#f8fafc; border-radius:8px;
  border: 1px solid var(--border); }
.detail-table { width:100%; border-collapse:collapse; }
.detail-table th { color:#475569; font-size:12px; padding:8px 10px; text-align:left;
  border-bottom:1px solid rgba(0,0,0,0.08); font-weight:600; }
.detail-table td { padding:9px 10px; font-size:13px; color:#334155;
  border-bottom:1px solid rgba(0,0,0,0.05); }
.mono { font-family:monospace; color:#64748b; }
/* ICU-06 低置信度行：黄色背景 + 左侧警告条 */
tr.low-confidence { background: #fff8e1; }
tr.low-confidence:hover td { background: #ffecb3; }
tr.low-confidence td:first-child::before {
  content: '⚠️'; margin-right: 4px; font-size: 12px;
}
</style>
