<template>
  <div>
    <div class="source">
      <span class="tag">数据源</span>{{ data.source_desc }}
      <span class="count" v-if="data.count > 0">共 {{ data.count }} 例</span>
    </div>
    <!-- 分母 / 汇总信息：不展示表格 -->
    <div v-if="data.part === 'denominator' && data.patients?.length === 1 && data.patients[0].patient_id === '—'" class="den-summary">
      {{ data.patients[0].name }}
    </div>
    <!-- 患者明细表格 -->
    <table v-else class="detail-table">
      <thead>
        <tr><th>住院号</th><th>姓名</th><th>床号</th><th>入科时间</th><th>{{ data.part === 'numerator' ? '在床天数' : '数值' }}</th></tr>
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
defineProps({ data: Object });
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
