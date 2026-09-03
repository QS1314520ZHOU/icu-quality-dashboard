<template>
  <div class="config-page">
    <header class="config-header">
      <div class="header-left">
        <h2>状态配置</h2>
      </div>
      <div class="actions">
        <button class="btn-ghost" @click="window.dispatchEvent(new CustomEvent('navigate-view', { detail: 'table' }))">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" style="width:14px;height:14px;margin-right:4px;vertical-align:-2px"><path d="M2 2h5l1 2h6v10H2V2zM6 8h4M6 11h2"/></svg>
          指标明细表
        </button>
        <button class="btn-primary" @click="save">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" style="width:14px;height:14px;margin-right:4px;vertical-align:-2px"><path d="M12 14H4a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1h5l3 3v8a1 1 0 0 1-1 1zM10 2v3h3M6 9h4"/></svg>
          保存配置
        </button>
      </div>
    </header>

    <div class="info-banner">
      <span class="info-icon">ℹ</span>
      <span>配置指标状态的颜色、告警级别及阈值范围，用于指标展示、告警触发和状态判断。</span>
    </div>

    <section class="panel">
      <div class="section-header">
        <span class="section-bar"></span>
        <h3>状态样式</h3>
      </div>
      <div class="status-grid">
        <div v-for="key in statusKeys" :key="key" class="status-card">
          <div class="card-label">
            <span class="dot" :style="{ background: form.meta[key].color }"></span>
            <strong>{{ metaLabels[key].label }}</strong>
            <span class="en">{{ metaLabels[key].en }}</span>
          </div>
          <div class="card-preview">
            <span class="badge-demo" :style="{ color: form.meta[key].color, background: form.meta[key].background }">{{ form.meta[key].label }}</span>
          </div>
          <div class="card-input">
            <input :value="form.meta[key].color" @input="updateColor(key, $event.target.value)" class="hex-input" placeholder="#000000" />
            <div class="swatch" :style="{ background: form.meta[key].color }"></div>
          </div>
          <div class="card-desc">{{ metaLabels[key].desc }}</div>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="section-header">
        <span class="section-bar"></span>
        <h3>阈值配置</h3>
      </div>
      <table class="config-table">
        <thead>
          <tr>
            <th class="col-code">编号</th>
            <th class="col-name">指标名称</th>
            <th class="col-dir">方向</th>
            <th class="col-range">阈值范围（从 - 到）</th>
            <th class="col-action">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="ind in indicators" :key="ind.code">
            <td class="cell-code">{{ displayCode(ind) }}</td>
            <td class="cell-name">{{ ind.name }}</td>
            <td class="cell-dir">
              <select v-model="form.thresholds[ind.code].direction" class="dir-select">
                <option value="range">区间最佳</option>
                <option value="higher_better">越高越好</option>
                <option value="lower_better">越低越好</option>
              </select>
            </td>
            <td class="cell-range">
              <div class="range-inputs">
                <label class="range-label">从</label>
                <input v-model.number="form.thresholds[ind.code].thresholds.good[0]" type="number" step="0.01" class="range-input" />
                <label class="range-label">至</label>
                <input v-model.number="form.thresholds[ind.code].thresholds.good[1]" type="number" step="0.01" class="range-input" />
              </div>
            </td>
            <td class="cell-action">
              <button class="reset-btn" @click="resetRow(ind.code)" title="恢复默认">↻</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="table-tip">
        <span class="info-icon tip-icon">ℹ</span>
        <span>提示：阈值范围的设置将用于指标状态的判断与告警触发，请确保配置合理。</span>
      </div>
    </section>

    <transition name="fade">
      <div v-if="saved" class="toast">✓ 配置已保存</div>
    </transition>
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

const metaLabels = {
  good:    { label: '正常',     en: 'Normal',       desc: '指标在正常范围内时的状态颜色' },
  warn:    { label: '预警',     en: 'Warning',      desc: '指标接近阈值时的预警状态颜色' },
  danger:  { label: '异常',     en: 'Abnormal',     desc: '指标超出阈值时的异常状态颜色' },
  unknown: { label: '趋势正常', en: 'Normal Trend', desc: '趋势分析中正常趋势的颜色' },
};

const indicators = INDICATORS.filter(ind => !ind.excludeFromStatusConfig);

function clone(value) { return JSON.parse(JSON.stringify(value)); }

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

function displayCode(ind) { return ind.displayCode || ind.code; }

function updateColor(key, val) {
  form.meta[key].color = val;
}

function resetRow(code) {
  const ind = INDICATORS.find(i => i.code === code);
  if (!ind) return;
  form.thresholds[code].direction = ind.direction;
  form.thresholds[code].thresholds = clone(ind.thresholds);
}

function save() {
  saveStatusConfig(clone(form));
  saved.value = true;
  setTimeout(() => { saved.value = false; }, 1600);
}
</script>

<style scoped>
.config-page {
  padding: 24px 32px;
  max-width: 1200px;
  margin: 0 auto;
}

.config-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.header-left h2 {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: var(--text-title);
}
.actions { display: flex; gap: 10px; }
.btn-ghost {
  background: #fff;
  color: #2B5EA7;
  border: 1px solid rgba(43,94,167,0.30);
  border-radius: 8px;
  padding: 8px 18px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-ghost:hover { background: rgba(43,94,167,0.06); border-color: #2B5EA7; }
.btn-primary {
  background: #2B5EA7;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 8px 20px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}
.btn-primary:hover { background: #237572; }

.info-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(43,94,167,0.06);
  border: 1px solid rgba(43,94,167,0.15);
  border-radius: 8px;
  padding: 10px 16px;
  margin-bottom: 20px;
  font-size: 13px;
  color: #4b5e6e;
}
.info-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px; height: 18px;
  border-radius: 50%;
  background: var(--brand);
  color: #fff;
  font-size: var(--fs-caption);
  font-weight: 700;
  flex-shrink: 0;
}

.panel {
  background: #fff;
  border: 1px solid #e6ebf2;
  border-radius: 12px;
  padding: 20px 24px;
  margin-bottom: 20px;
  box-shadow: 0 1px 3px rgba(17,24,39,0.04);
}
.section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
}
.section-bar {
  width: 4px;
  height: 20px;
  border-radius: 2px;
  background: #2B5EA7;
}
.section-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-title);
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
.status-card {
  background: #fff;
  border: 1px solid #edf1f7;
  border-radius: 10px;
  padding: 16px;
  transition: box-shadow 0.2s;
}
.status-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.card-label {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
}
.card-label .dot {
  width: 10px; height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.card-label strong {
  font-size: 14px;
  color: var(--text-title);
  font-weight: 600;
}
.card-label .en {
  font-size: 12px;
  color: #94a3b8;
  font-weight: 400;
}
.card-preview {
  margin-bottom: 12px;
}
.badge-demo {
  display: inline-block;
  padding: 3px 14px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
}
.card-input {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.hex-input {
  flex: 1;
  border: 1px solid #d9e2ef;
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 13px;
  font-family: 'Cascadia Code', 'Consolas', monospace;
  color: #374151;
  background: #f9fafb;
  transition: border-color 0.2s;
}
.hex-input:focus { outline: none; border-color: #2B5EA7; }
.swatch {
  width: 32px; height: 32px;
  border-radius: 6px;
  border: 2px solid #e5e7eb;
  flex-shrink: 0;
  transition: background 0.2s;
}
.card-desc {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
}

.config-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}
.config-table th,
.config-table td {
  padding: 12px 14px;
  text-align: left;
  font-size: 13px;
  border-bottom: 1px solid #f0f2f5;
}
.config-table th {
  background: #f8fafc;
  color: #64748b;
  font-weight: 600;
  font-size: 12px;
  white-space: nowrap;
}
.config-table tbody tr:hover { background: #f6faf9; }
.col-code { width: 100px; }
.col-name { width: auto; }
.col-dir  { width: 140px; }
.col-range { width: 300px; }
.col-action { width: 80px; text-align: center; }
.cell-code {
  font-family: 'Cascadia Code', 'Consolas', monospace;
  color: #64748b;
  font-weight: 500;
}
.cell-name { color: var(--text-title); }
.dir-select {
  width: 100%;
  border: 1px solid #d9e2ef;
  border-radius: 6px;
  padding: 7px 10px;
  font-size: 13px;
  color: #374151;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.2s;
  appearance: auto;
}
.dir-select:focus { outline: none; border-color: #2B5EA7; }
.range-inputs {
  display: flex;
  align-items: center;
  gap: 6px;
}
.range-label {
  font-size: 12px;
  color: #94a3b8;
  flex-shrink: 0;
}
.range-input {
  width: 90px;
  border: 1px solid #d9e2ef;
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
  color: #374151;
  text-align: center;
  transition: border-color 0.2s;
}
.range-input:focus { outline: none; border-color: #2B5EA7; }
.cell-action { text-align: center; }
.reset-btn {
  width: 30px; height: 30px;
  border-radius: 50%;
  border: 1px solid #d9e2ef;
  background: #fff;
  color: #2B5EA7;
  font-size: 16px;
  font-weight: 700;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}
.reset-btn:hover { background: rgba(43,94,167,0.08); border-color: #2B5EA7; }

.table-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  padding: 10px 0 0;
  border-top: 1px solid #f0f2f5;
  font-size: 12px;
  color: #94a3b8;
}
.tip-icon { background: #94a3b8; }

.toast {
  position: fixed;
  top: 24px;
  right: 24px;
  background: #2B5EA7;
  color: #fff;
  padding: 10px 22px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  box-shadow: 0 4px 12px rgba(43,94,167,0.30);
  z-index: 9999;
}
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

@media (max-width: 900px) {
  .status-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 600px) {
  .status-grid { grid-template-columns: 1fr; }
  .config-page { padding: 16px; }
}
</style>
