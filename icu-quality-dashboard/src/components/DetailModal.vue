<template>
  <div>
    <div class="source">
      <span class="tag">数据源</span>{{ data.source_desc }}
      <span class="count" v-if="data.count > 0">
        共 {{ data.count }} 例<span v-if="data.has_more">，先显示 {{ data.patients?.length || 0 }} 例</span>
      </span>
    </div>
    <div v-if="data.loading" class="loading">明细加载中...</div>
    <div v-else-if="data.error" class="empty">{{ data.error }}</div>
    <div v-else-if="!data.patients?.length" class="empty">暂无明细</div>
    <!-- 分母汇总 -->
    <div v-else-if="isSummary" class="den-summary">{{ data.patients[0].name }}</div>
    <!-- 表格 -->
    <table v-else class="detail-table">
      <thead>
        <tr v-if="isAssessmentNumerator">
          <th>{{ col1 }}</th><th>姓名</th><th>评估来源</th><th>评分中文名</th><th>分值</th><th>评估时间</th>
        </tr>
        <tr v-else-if="isAirwayDetail">
          <th>{{ col1 }}</th><th>姓名</th><th>管道类型</th><th>插管时间</th><th>拔管时间</th><th>{{ airwayExtraCol }}</th><th>例次</th>
        </tr>
        <tr v-else-if="isICU14">
          <th>{{ col1 }}</th><th>姓名</th><th>转入类型</th><th>转入计划</th><th>手术名称</th><th>转入ICU时间</th><th>依据</th>
        </tr>
        <tr v-else-if="isICU15">
          <th>{{ col1 }}</th><th>姓名</th><th>出科时间</th><th>重返入科时间</th><th>来源</th><th>依据</th>
        </tr>
        <tr v-else-if="isICU18">
          <th>{{ col1 }}</th><th>姓名</th><th>脑损伤类别</th><th>入分母来源</th><th>命中依据</th><th>是否评估</th><th>首次评估</th>
        </tr>
        <tr v-else-if="isICU19">
          <th>{{ col1 }}</th><th>姓名</th><th>入科时间</th><th>{{ icu19TimeCol }}</th><th>{{ icu19SourceCol }}</th><th>{{ icu19EvidenceCol }}</th><th>判定说明</th>
        </tr>
        <tr v-else-if="isTriTube">
          <th>{{ col1 }}</th><th>姓名</th><th>{{ triTubeCol3 }}</th><th>{{ triTubeCol4 }}</th><th>{{ triTubeCol5 }}</th><th>依据</th>
        </tr>
        <tr v-else>
          <th>{{ col1 }}</th><th>姓名</th><th>{{ col3 }}</th><th>{{ col4 }}</th><th>{{ col5 }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="p in data.patients" :key="p.detail_id || p.patient_id" :class="rowClass(p)"
            :title="p.admission_source === 'low_confidence' ? '⚠️ AI判定置信度<0.6，待人工复核' : ''">
          <td class="mono">{{ p.patient_id }}</td>
          <td>{{ p.name }}</td>
          <template v-if="isAssessmentNumerator">
            <td>{{ p.bed_no }}</td>
            <td>{{ p.dept }}</td>
            <td>{{ p.value || '—' }}</td>
            <td>{{ p.admit_time }}</td>
          </template>
          <template v-else-if="isAirwayDetail">
            <td>{{ p.tube_type }}</td>
            <td>{{ p.tube_start }}</td>
            <td>{{ p.tube_end }}</td>
            <td>{{ airwayExtraValue(p) }}</td>
            <td>1</td>
          </template>
          <template v-else-if="isICU14">
            <td>{{ p.admissionType || p.bed_no }}</td>
            <td>{{ p.admissionPlan || p.admission_source || '/' }}</td>
            <td>{{ p.operation_name || p.dept || '/' }}</td>
            <td>{{ p.icuAdmissionTime || p.admit_time }}</td>
            <td>{{ p.basis || '/' }}</td>
          </template>
          <template v-else-if="isICU15">
            <td>{{ p.icuDischargeTime || p.admit_time || '/' }}</td>
            <td>{{ p.reIcuAdmissionTime || p.discharge_time || '/' }}</td>
            <td>{{ p.event_source || p.admission_source || '/' }}</td>
            <td>{{ p.basis || '/' }}</td>
          </template>
          <template v-else-if="isICU18">
            <td>{{ p.brain_category || p.bed_no || '/' }}</td>
            <td>{{ p.den_source || p.dept || '/' }}</td>
            <td>{{ p.evidence || p.basis || '/' }}</td>
            <td>{{ p.assessed || '/' }}</td>
            <td>{{ p.firstAssessTime || p.discharge_time || '/' }} {{ p.assessSource || '' }}</td>
          </template>
          <template v-else-if="isICU19">
            <td>{{ p.icuAdmissionTime || p.admit_time || '/' }}</td>
            <td>{{ props.data?.part === 'numerator' ? (p.enStartTime || p.discharge_time || '/') : (p.windowResult || p.admission_source || '/') }}</td>
            <td>{{ p.enSource || p.bed_no || '/' }}</td>
            <td>{{ icu19Evidence(p) }}</td>
            <td>{{ p.basis || '/' }}</td>
          </template>
          <template v-else-if="isTriTube">
            <td>{{ triTubeValue3(p) }}</td>
            <td>{{ triTubeValue4(p) }}</td>
            <td>{{ triTubeValue5(p) }}</td>
            <td>{{ p.basis || p.admission_source || '/' }}</td>
          </template>
          <template v-else>
            <td>{{ p.bed_no }}</td>
            <td>{{ p.admit_time }}</td>
            <td>{{ p.value ?? '—' }}</td>
          </template>
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
const isICU11 = computed(() => props.data?.code === 'ICU-11');
const isICU12 = computed(() => props.data?.code === 'ICU-12');
const isICU13 = computed(() => props.data?.code === 'ICU-13');
const isICU14 = computed(() => props.data?.code === 'ICU-14');
const isICU15 = computed(() => props.data?.code === 'ICU-15');
const isICU18 = computed(() => props.data?.code === 'ICU-18');
const isICU19 = computed(() => props.data?.code === 'ICU-19');
const isTriTube = computed(() => ['ICU-16', 'ICU-17', 'CAUTI'].includes(props.data?.code));
const isAssessmentNumerator = computed(() =>
  props.data?.part === 'numerator' && (isICU09.value || isICU10.value)
);
const isAirwayDetail = computed(() => isICU12.value || isICU13.value);
const airwayExtraCol = computed(() => {
  if (isICU13.value && props.data?.part === 'numerator') return '再置管';
  if (isICU12.value && props.data?.part === 'numerator') return '非计划';
  return '说明';
});
const airwayExtraValue = (p) => {
  if (isICU13.value && props.data?.part === 'numerator') {
    return p.reinsert_start ? `${p.reinsert_type} ${p.reinsert_start}` : '';
  }
  if (isICU12.value && props.data?.part === 'numerator') return p.unplanned ? '是' : '否';
  return '';
};
const triTubeCol3 = computed(() => props.data?.part === 'numerator' ? '感染类型' : '设备/导管');
const triTubeCol4 = computed(() => props.data?.part === 'numerator' ? '诊断时间' : '天数');
const triTubeCol5 = computed(() => {
  if (props.data?.part === 'numerator') return '备注';
  if (props.data?.code === 'ICU-16') return '通气方式 / 记录点数';
  return '管道类型 / 置管点数';
});
const triTubeValue3 = (p) => props.data?.part === 'numerator'
  ? (p.diseaseType || p.bed_no || '/')
  : (p.device_type || p.bed_no || '/');
const triTubeValue4 = (p) => props.data?.part === 'numerator'
  ? (p.diagnosisTime || p.admit_time || '/')
  : (p.device_days ? `${p.device_days}天` : p.admit_time ? `${p.admit_time}天` : '/');
const triTubeValue5 = (p) => {
  if (props.data?.part === 'numerator') return p.notes || p.dept || '/';
  return `${p.tube_type || p.device_value || p.dept || '/'} / ${p.tube_points || 0}`;
};
const icu19TimeCol = computed(() => props.data?.part === 'numerator' ? 'EN启动时间' : 'EN启动情况');
const icu19SourceCol = computed(() => props.data?.part === 'numerator' ? '启动来源' : '判定来源');
const icu19EvidenceCol = computed(() => props.data?.part === 'numerator' ? '命中证据' : '命中/禁忌证');
const icu19Evidence = (p) => {
  const hit = p.enHit || p.enRoute || p.enDrug || '/';
  return p.contraindication ? `${hit}；禁忌证：${p.contraindication}` : hit;
};
const col1 = computed(() => isStaff.value ? '账号' : '住院号');
const col3 = computed(() => {
  if (isStaff.value) return '职称';
  if (isICU08.value && props.data?.part === 'denominator') return 'P/F  PEEP';
  if (isICU08.value && props.data?.part === 'numerator') return '俯卧次数';
  if (isICU06.value && props.data?.part === 'denominator') return '抗菌药 [目的]';
  if (isICU06.value && props.data?.part === 'numerator') return '送检项目';
  if (isICU07.value && props.data?.part === 'numerator') return '预防措施';
  if (isICU11.value) return '转归';
  if (isICU13.value && props.data?.part === 'numerator') return '拔管→再置管';
  if (isICU12.value || isICU13.value) return '管道类型';
  return '床号';
});
const col4 = computed(() => {
  if (isStaff.value) return '入职日期';
  if (isICU08.value && props.data?.part === 'denominator') return '纳入路径';
  if (isICU08.value && props.data?.part === 'numerator') return '首次俯卧时间';
  if (isICU06.value && props.data?.part === 'denominator') return '给药 & 判定理由';
  if (isICU06.value && props.data?.part === 'numerator') return '送检时间';
  if (isICU07.value && props.data?.part === 'numerator') return '医嘱示例';
  if (isICU11.value) return '首次APACHEⅡ时间';
  if (isICU13.value && props.data?.part === 'numerator') return '拔管/再置管时间';
  if (isICU12.value || isICU13.value) return '拔管时间';
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
  if (isICU11.value) return '预计死亡率';
  if (isICU12.value || isICU13.value) return '例次';
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
.loading, .empty { font-size:14px; color:#64748b; text-align:center; padding:34px 20px;
  background:#f8fafc; border:1px solid var(--border); border-radius:8px; }
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
