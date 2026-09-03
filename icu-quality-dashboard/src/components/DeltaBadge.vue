<template>
  <span
    class="delta-badge"
    :class="[cssClass, { 'small-sample': smallSample }]"
    :title="tooltip"
  >
    <svg v-if="arrow === '↑'" class="delta-arrow" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 10V2M2 6l4-4 4 4"/></svg>
    <svg v-else-if="arrow === '↓'" class="delta-arrow" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2v8M2 6l4 4 4-4"/></svg>
    <svg v-else-if="arrow === '→'" class="delta-arrow" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 6h8M6 2l4 4-4 4"/></svg>
    <span class="delta-text tabular-nums">{{ text }}</span>
    <span v-if="label" class="delta-label">{{ label }}</span>
    <span v-if="smallSample" class="n-small" title="分母较小（<30），波动不代表趋势">n 小</span>
  </span>
</template>

<script setup>
/**
 * DeltaBadge — 环比/同比徽标
 * 箭头图标(内联 SVG) + 数值 + 标签，语义色走 good/warn/danger/faint。
 */
const props = defineProps({
  /** 显示文本，如 '+2.3pp' */
  text: { type: String, default: '—' },
  /** tooltip 提示 */
  tooltip: { type: String, default: '' },
  /** CSS 语义类：'good' | 'bad' | 'faint' */
  cssClass: { type: String, default: 'faint' },
  /** 箭头方向：'↑' | '↓' | '→' | '' */
  arrow: { type: String, default: '' },
  /** 标签文字，如 '环比' / '同比' */
  label: { type: String, default: '' },
  /** 是否小样本 */
  smallSample: { type: Boolean, default: false },
});
</script>

<style scoped>
.delta-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  line-height: 1;
  padding: 2px 6px;
  border-radius: 4px;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  vertical-align: middle;
}

/* 语义色 */
.delta-badge.good {
  color: var(--good);
  background: var(--good-weak);
}
.delta-badge.bad {
  color: var(--danger);
  background: var(--danger-weak);
}
.delta-badge.faint {
  color: var(--text-faint);
  background: var(--bg-subtle);
}

.delta-arrow {
  width: 10px;
  height: 10px;
  flex-shrink: 0;
}

.delta-text {
  font-weight: 600;
}

.delta-label {
  color: var(--text-faint);
  font-weight: 400;
  font-size: 11px;
}

.n-small {
  color: var(--text-faint);
  font-size: 11px;
  font-weight: 400;
  margin-left: 2px;
}

/* 紧凑两行模式 */
.delta-badge.compact {
  flex-wrap: wrap;
  gap: 1px 3px;
}
</style>
