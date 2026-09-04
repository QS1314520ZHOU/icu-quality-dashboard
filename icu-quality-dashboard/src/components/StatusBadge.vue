<template>
  <span class="status-badge" :class="statusClass" :title="tooltipText">
    <span class="status-icon">{{ icon }}</span>
    <span class="status-text" v-if="showText">{{ text }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  value: { type: [Boolean, null], default: null },
  tooltip: { type: String, default: '' },
  showText: { type: Boolean, default: false },
})

const statusClass = computed(() => {
  if (props.value === true) return 'status-ok'
  if (props.value === false) return 'status-fail'
  return 'status-na'
})

const icon = computed(() => {
  if (props.value === true) return '✅'
  if (props.value === false) return '❌'
  return '—'
})

const text = computed(() => {
  if (props.value === true) return '达标'
  if (props.value === false) return '未达标'
  return '未测量'
})

const tooltipText = computed(() => {
  if (props.tooltip) return props.tooltip
  if (props.value === true) return '达标 (true)'
  if (props.value === false) return '未达标 (false)'
  return '未测量 (null) - 不参与完成计算'
})
</script>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.85em;
  white-space: nowrap;
}

.status-ok {
  background: var(--success-weak, #ecfdf5);
  color: var(--success, #10b981);
}

.status-fail {
  background: var(--danger-weak, #fef2f2);
  color: var(--danger, #ef4444);
}

.status-na {
  background: var(--bg-subtle);
  color: var(--text-sub);
}

.status-icon {
  font-size: 0.9em;
}

.status-text {
  font-size: 0.85em;
}
</style>
