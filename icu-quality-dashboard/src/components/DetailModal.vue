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
        <tr v-for="p in data.patients" :key="p.patient_id">
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
const isICU08 = computed(() => props.data?.code === 'ICU-08');
const col1 = computed(() => isStaff.value ? '账号' : '住院号');
const col3 = computed(() => {
  if (isStaff.value) return '职称';
  if (isICU08.value && props.data?.part === 'denominator') return 'P/F  PEEP';
  if (isICU08.value && props.data?.part === 'numerator') return '俯卧次数';
  return '床号';
});
const col4 = computed(() => {
  if (isStaff.value) return '入职日期';
  if (isICU08.value && props.data?.part === 'denominator') return '纳入路径';
  if (isICU08.value && props.data?.part === 'numerator') return '首次俯卧时间';
  return '入科时间';
});
const col5 = computed(() => {
  if (isStaff.value) return '人数';
  if (isICU08.value && props.data?.part === 'denominator') return 'P/F值';
  if (isICU08.value && props.data?.part === 'numerator') return '俯卧总次数';
  if (props.data?.code === 'ICU-04' && props.data?.part === 'numerator') return 'APACHEⅡ';
  if (props.data?.code === 'ICU-04' && props.data?.part === 'denominator') return '在科';
  if (props.data?.part === 'numerator' && props.data?.code === 'ICU-01') return '在床天数';
  return '数值';
});
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
</style>
