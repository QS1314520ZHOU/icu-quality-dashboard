<template>
  <div class="config-page">
    <header class="config-header">
      <div>
        <h2>状态配置</h2>
        <p>配置达标、预警、异常文案颜色，以及各指标判定区间。</p>
      </div>
      <div class="actions">
        <span v-if="saved" class="saved">已保存</span>
        <button class="ghost" @click="reset">恢复默认</button>
        <button class="primary" @click="save">保存配置</button>
      </div>
    </header>

    <section class="panel">
      <h3>状态样式</h3>
      <div class="status-grid">
        <label v-for="key in statusKeys" :key="key" class="status-row">
          <span class="badge" :style="badgeStyle(key)">
            <i :style="{ background: form.meta[key].color }"></i>{{ form.meta[key].label }}
          </span>
          <input v-model="form.meta[key].label" />
          <input v-model="form.meta[key].color" type="color" />
        </label>
      </div>
    </section>

    <section class="panel">
      <h3>指标阈值</h3>
      <table class="config-table">
        <thead>
          <tr>
            <th>编码</th>
            <th>指标名称</th>
            <th>方向</th>
            <th>达标区间</th>
            <th>预警区间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="ind in indicators" :key="ind.code">
            <td class="mono">{{ displayCode(ind) }}</td>
            <td>{{ ind.name }}</td>
            <td>
              <select v-model="form.thresholds[ind.code].direction">
                <option value="higher_better">越高越好</option>
                <option value="lower_better">越低越好</option>
                <option value="range">区间最佳</option>
              </select>
            </td>
            <td class="range">
              <input v-model.number="form.thresholds[ind.code].thresholds.good[0]" type="number" step="0.01" />
              <span>至</span>
              <input v-model.number="form.thresholds[ind.code].thresholds.good[1]" type="number" step="0.01" />
            </td>
            <td class="range">
              <input v-model.number="form.thresholds[ind.code].thresholds.warn[0]" type="number" step="0.01" />
              <span>至</span>
              <input v-model.number="form.thresholds[ind.code].thresholds.warn[1]" type="number" step="0.01" />
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue';
import {
  DEFAULT_STATUS_META,
  INDICATORS,
  getStatusConfig,
  saveStatusConfig,
} from '../config/indicators.js';

const statusKeys = ['good', 'warn', 'danger', 'unknown'];
const indicators = INDICATORS;

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function defaults() {
  return {
    meta: clone(DEFAULT_STATUS_META),
    thresholds: Object.fromEntries(
      INDICATORS.map(ind => [
        ind.code,
        { direction: ind.direction, thresholds: clone(ind.thresholds) },
      ])
    ),
  };
}

const form = reactive(clone(getStatusConfig()));
const saved = ref(false);

function displayCode(ind) {
  return ind.displayCode || ind.code;
}

function badgeStyle(key) {
  return {
    color: form.meta[key].color,
    background: form.meta[key].background || 'rgba(148,163,184,0.10)',
  };
}

function replaceForm(next) {
  Object.keys(form.meta).forEach(key => delete form.meta[key]);
  Object.assign(form.meta, clone(next.meta));
  Object.keys(form.thresholds).forEach(key => delete form.thresholds[key]);
  Object.assign(form.thresholds, clone(next.thresholds));
}

function reset() {
  replaceForm(defaults());
}

function save() {
  saveStatusConfig(clone(form));
  saved.value = true;
  setTimeout(() => { saved.value = false; }, 1600);
}
</script>

<style scoped>
.config-page { padding:20px 28px; }
.config-header { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:16px; }
h2 { margin:0; color:#1e293b; font-size:20px; }
p { margin:6px 0 0; color:#64748b; font-size:13px; }
.actions { display:flex; gap:8px; }
.saved { align-self:center; color:#15966b; font-size:13px; }
button { border-radius:7px; padding:8px 16px; font-size:13px; cursor:pointer; }
.ghost { background:#fff; color:#0052d9; border:1px solid rgba(0,82,217,0.25); }
.primary { background:#0052d9; color:#fff; border:1px solid #0052d9; }
.panel { background:#fff; border:1px solid #e6ebf2; border-radius:8px; padding:14px; margin-bottom:14px; }
h3 { margin:0 0 12px; color:#2c7be5; font-size:14px; }
.status-grid { display:grid; grid-template-columns:repeat(4, minmax(170px, 1fr)); gap:10px; }
.status-row { display:grid; grid-template-columns:80px 1fr 42px; gap:8px; align-items:center; }
.badge { display:inline-flex; align-items:center; gap:5px; width:max-content; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:600; }
.badge i { width:5px; height:5px; border-radius:50%; display:inline-block; }
input, select { border:1px solid #d9e2ef; border-radius:6px; padding:6px 8px; font-size:13px; background:#fff; }
input[type="color"] { padding:2px; height:32px; width:42px; }
.config-table { width:100%; border-collapse:collapse; table-layout:fixed; }
.config-table th, .config-table td { border-bottom:1px solid #edf1f7; padding:9px 10px; text-align:left; font-size:13px; }
.config-table th { color:#64748b; background:#f8fafc; font-size:12px; }
.mono { font-family:'Cascadia Code','Consolas',monospace; color:#64748b; }
.range { display:flex; align-items:center; gap:6px; }
.range input { width:84px; }
</style>
