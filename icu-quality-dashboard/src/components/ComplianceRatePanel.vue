<template>
  <div class="compliance-panel" :class="{ dark }">
    <div v-for="cell in cells" :key="cell.key" class="cp-cell" :class="{ empty: cell.empty }">
      <div class="cp-label">{{ cell.label }}</div>
      <div class="cp-rate tabular-nums">{{ cell.percentText }}</div>
      <div class="cp-meta">
        <span class="cp-fraction tabular-nums">{{ cell.empty ? '—' : `${cell.good}/${cell.valid}` }}</span>
        <span v-if="cell.devCount" class="cp-dev">偏离 {{ cell.devCount }}</span>
      </div>
      <div class="cp-bar">
        <i class="cp-fill" :style="{ width: (cell.empty ? 0 : cell.percent) + '%' }"></i>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * ComplianceRatePanel — 达标率总览（结构 / 过程 / 结果 / 总体）
 * 呈现为百分比 + 细进度条，不使用红绿灯三色状态。
 */
import { computed } from 'vue';

const props = defineProps({
  /** { structure: {good,warn,danger,total}, process: {...}, outcome: {...} } */
  zoneStats: { type: Object, required: true },
  /** 总体计数 { good, warn, danger, unknown } */
  overallCounts: { type: Object, default: null },
  dark: { type: Boolean, default: false },
});

function cellFrom(label, key, s) {
  const valid = (s?.good || 0) + (s?.warn || 0) + (s?.danger || 0);
  const good = s?.good || 0;
  const devCount = (s?.warn || 0) + (s?.danger || 0);
  const percent = valid > 0 ? Math.round((good / valid) * 1000) / 10 : 0;
  return {
    key,
    label,
    good,
    valid,
    devCount,
    percent,
    percentText: valid > 0 ? `${percent.toFixed(1)}%` : '无数据',
    empty: valid === 0,
  };
}

const cells = computed(() => {
  const z = props.zoneStats || {};
  const list = [
    cellFrom('结构', 'structure', z.structure),
    cellFrom('过程', 'process', z.process),
    cellFrom('结果', 'outcome', z.outcome),
  ];
  const c = props.overallCounts;
  if (c) {
    list.push(cellFrom('总体', 'overall', {
      good: c.good, warn: c.warn, danger: c.danger,
    }));
  }
  return list;
});
</script>

<style scoped>
.compliance-panel {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.cp-cell {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px 10px;
  min-width: 0;
}
.cp-label {
  font-size: 12px;
  color: var(--text-sub);
  letter-spacing: 0.04em;
}
.cp-rate {
  font-size: 26px;
  font-weight: 650;
  color: var(--text-title);
  line-height: 1.25;
  margin-top: 2px;
}
.cp-cell.empty .cp-rate { font-size: 16px; color: var(--text-faint); font-weight: 600; }
.cp-cell.empty { opacity: 0.85; }
.cp-meta {
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-size: 12px;
  color: var(--text-faint);
  margin-bottom: 8px;
}
.cp-dev { color: var(--text-sub); }
.cp-bar {
  height: 3px;
  border-radius: 2px;
  background: var(--bg-subtle, var(--border));
  overflow: hidden;
}
.cp-fill {
  display: block;
  height: 100%;
  background: #3b6fd4;
  border-radius: 2px;
}

.compliance-panel.dark .cp-cell {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(120, 160, 220, 0.18);
}
.compliance-panel.dark .cp-label { color: #8fa3c0; }
.compliance-panel.dark .cp-rate { color: #e8eef8; }
.compliance-panel.dark .cp-meta { color: #6b7f9a; }
.compliance-panel.dark .cp-bar { background: rgba(255, 255, 255, 0.08); }
.compliance-panel.dark .cp-fill { background: #5b8def; }

@media (max-width: 900px) {
  .compliance-panel { grid-template-columns: repeat(2, 1fr); }
}
</style>
