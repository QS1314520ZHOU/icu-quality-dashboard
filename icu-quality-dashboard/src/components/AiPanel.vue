<template>
  <div class="ai-panel">
    <div class="ai-head">
      <span class="ai-icon">🩺</span> AI 质控分析
    </div>
    <div class="ai-summary">{{ analysis.summary || '分析中…' }}</div>
    <div class="ai-abnormal" v-if="analysis.abnormal?.length">
      <div class="sub-title">⚠ 异常指标预警</div>
      <div class="ab-item" v-for="a in analysis.abnormal" :key="a.code">
        <span class="ab-name">{{ a.name }}</span>
        <span class="ab-val" :class="a.level">{{ a.value }}</span>
      </div>
    </div>
    <div class="ai-tip">
      ※ AI 仅辅助质控分析，不替代临床诊疗判断
    </div>
  </div>
</template>

<script setup>
defineProps({ analysis: Object });
</script>

<style scoped>
.ai-panel { display: flex; flex-direction: column; height: 100%; }
.ai-head { font-size: 15px; color: #0052d9; font-weight: bold; margin: 8px 0 12px; }
.ai-icon { margin-right: 6px; }
.ai-summary {
  font-size: 13px; line-height: 1.8; color: #334155;
  background: #f0f6ff; padding: 12px; border-radius: 6px;
  border: 1px solid rgba(0,82,217,0.12);
}
.sub-title { font-size: 13px; color: #d97706; margin: 16px 0 8px; font-weight: 600; }
.ab-item { display: flex; justify-content: space-between; padding: 8px 10px;
  background: rgba(239,68,68,0.05); border-radius: 4px; margin-bottom: 6px; border: 1px solid rgba(239,68,68,0.08); }
.ab-name { font-size: 13px; color: #475569; }
.ab-val { font-weight: bold; }
.ab-val.warn { color: #f59e0b; }
.ab-val.danger { color: #ef4444; }
.ai-tip { margin-top: auto; padding-top: 12px; font-size: 11px; color: #64748b;
  border-top: 1px dashed rgba(0,0,0,0.08); }
</style>
