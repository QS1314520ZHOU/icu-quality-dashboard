<template>
  <div class="comparison-table-wrap">
    <div class="table-header">
      <span class="table-title">环比同比总表</span>
      <button v-if="displayRows.length > 10" class="toggle-btn" @click="expanded = !expanded">
        {{ expanded ? '收起' : '展开全部' }} ({{ allRows.length }})
      </button>
    </div>
    <div class="table-scroll">
      <table class="comp-table">
        <thead>
          <tr>
            <th class="col-code">指标</th>
            <th class="col-name">名称</th>
            <th class="col-val">本期</th>
            <th class="col-val">上期</th>
            <th class="col-val">去年同期</th>
            <th class="col-delta sortable" @click="toggleSort('mom')">
              环比 {{ sortKey === 'mom' ? (sortDir === 'asc' ? '↑' : '↓') : '' }}
            </th>
            <th class="col-delta sortable" @click="toggleSort('yoy')">
              同比 {{ sortKey === 'yoy' ? (sortDir === 'asc' ? '↑' : '↓') : '' }}
            </th>
            <th class="col-status">状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in displayRows" :key="row.code" :class="row.status" @click="$emit('row-click', row._row || row)">
            <td class="col-code">{{ row.displayCode }}</td>
            <td class="col-name">{{ row.name }}</td>
            <td class="col-val tabular-nums">{{ row.currentText }}</td>
            <td class="col-val tabular-nums">{{ row.previousText }}</td>
            <td class="col-val tabular-nums">{{ row.yoyText }}</td>
            <td class="col-delta" :class="row.momClass">
              <span class="delta-cell tabular-nums">{{ row.momText }}</span>
              <span v-if="row.momSmall" class="n-small">n 小</span>
            </td>
            <td class="col-delta" :class="row.yoyClass">
              <span class="delta-cell tabular-nums">{{ row.yoyText }}</span>
              <span v-if="row.yoySmall" class="n-small">n 小</span>
            </td>
            <td class="col-status">
              <span class="status-dot" :class="row.status"></span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
/**
 * ComparisonTable — 对比表
 * 列 = 指标 / 本期 / 上期 / 去年同期 / 环比 / 同比 / 状态
 * 环比同比单元格用 *-weak 底色做热力，支持排序，表头吸顶。
 */
import { ref, computed } from 'vue';
import { INDICATORS } from '../config/indicators.js';
import { getMoM, getYoY, formatDelta, formatValue } from '../utils/compare.js';

const props = defineProps({
  /** rows 数组 */
  rows: { type: Array, default: () => [] },
  /** trend 数据 */
  trend: { type: Object, default: () => ({}) },
  /** months 数组 */
  months: { type: Array, default: () => [] },
  /** 去年同期 trend */
  yoyTrend: { type: Object, default: null },
  /** 去年同期 months */
  yoyMonths: { type: Array, default: null },
  /** rowsByCode */
  rowsByCode: { type: Object, default: () => ({}) },
});

const emit = defineEmits(['row-click']);

const expanded = ref(false);
const sortKey = ref('');
const sortDir = ref('asc');

function toggleSort(key) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc';
  } else {
    sortKey.value = key;
    sortDir.value = 'asc';
  }
}

function buildRow(row) {
  const ind = INDICATORS.find(i => i.code === row.code);
  const displayCode = ind?.displayCode || row.code;

  const mom = getMoM(row.code, props.trend, props.months, row.denominator);
  const yoy = getYoY(row.code, props.trend, props.months, props.yoyTrend, props.yoyMonths, row.denominator);
  const momFmt = formatDelta(mom, 'mom');
  const yoyFmt = formatDelta(yoy, 'yoy');

  return {
    _row: row, // 原始行引用，供 click 下钻
    code: row.code,
    displayCode,
    name: row.name,
    status: row.status || 'unknown',
    value: row.value,
    unit: row.unit || '',
    currentText: formatValue(row.value, row.code) + (row.unit || ''),
    previousText: mom ? formatValue(mom.previous, row.code) + (row.unit || '') : '—',
    yoyText: yoy ? formatValue(yoy.yoy, row.code) + (row.unit || '') : '—',
    momText: momFmt.text,
    momClass: momFmt.cssClass,
    momSmall: momFmt.smallSample,
    momDelta: mom?.delta,
    yoyText: yoyFmt.text,
    yoyClass: yoyFmt.cssClass,
    yoySmall: yoyFmt.smallSample,
    yoyDelta: yoy?.delta,
  };
}

const allRows = computed(() => {
  let list = props.rows
    .filter(r => {
      const ind = INDICATORS.find(i => i.code === r.code);
      return !ind?.excludeFromAlert && !ind?.excludeFromStatusConfig;
    })
    .map(buildRow);

  // 排序
  if (sortKey.value) {
    const key = sortKey.value === 'mom' ? 'momDelta' : 'yoyDelta';
    list = [...list].sort((a, b) => {
      const va = a[key] ?? 0;
      const vb = b[key] ?? 0;
      return sortDir.value === 'asc' ? va - vb : vb - va;
    });
  }

  return list;
});

const displayRows = computed(() => {
  if (expanded.value) return allRows.value;
  return allRows.value.slice(0, 10);
});
</script>

<style scoped>
.comparison-table-wrap {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  overflow: hidden;
  box-shadow: var(--shadow-card);
}

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}

.table-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-title);
}

.toggle-btn {
  background: var(--brand-weak);
  border: 1px solid rgba(30, 94, 184, 0.2);
  border-radius: 6px;
  color: var(--brand);
  font-size: 12px;
  padding: 4px 10px;
  cursor: pointer;
}

.toggle-btn:hover {
  background: rgba(30, 94, 184, 0.12);
}

.table-scroll {
  overflow-x: auto;
  max-height: 500px;
  overflow-y: auto;
}

.comp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.comp-table thead {
  position: sticky;
  top: 0;
  z-index: 2;
}

.comp-table th {
  background: var(--bg-header);
  color: var(--text-sub);
  font-weight: 600;
  font-size: 12px;
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

.comp-table th.sortable {
  cursor: pointer;
  user-select: none;
}

.comp-table th.sortable:hover {
  color: var(--brand);
}

.comp-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  color: var(--text-body);
  white-space: nowrap;
}

.comp-table tr {
  height: 40px;
  transition: background 0.15s;
  cursor: pointer;
}

.comp-table tbody tr:hover {
  background: var(--bg-hover);
}

.col-code {
  color: var(--brand);
  font-weight: 700;
  font-size: 12px;
  width: 80px;
}

.col-name {
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.col-val {
  text-align: right;
  min-width: 70px;
}

.col-delta {
  text-align: center;
  min-width: 80px;
}

.col-delta.good {
  background: var(--good-weak);
  color: var(--good);
}

.col-delta.bad {
  background: var(--danger-weak);
  color: var(--danger);
}

.col-delta.faint {
  background: var(--bg-subtle);
  color: var(--text-faint);
}

.delta-cell {
  font-weight: 600;
}

.n-small {
  font-size: 11px;
  color: var(--text-faint);
  margin-left: 4px;
}

.col-status {
  text-align: center;
  width: 50px;
}

.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.status-dot.good {
  background: var(--good);
}

.status-dot.warn {
  background: var(--warn);
}

.status-dot.danger {
  background: var(--danger);
}

.status-dot.unknown {
  background: var(--text-faint);
}
</style>
