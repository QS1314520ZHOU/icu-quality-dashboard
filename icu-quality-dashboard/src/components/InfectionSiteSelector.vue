<template>
  <div class="infection-site-selector">
    <h4>感染部位选择</h4>

    <!-- 主要感染部位 -->
    <div class="form-group">
      <label>主要感染部位</label>
      <div class="site-grid">
        <button
          v-for="site in VALID_SITES"
          :key="site"
          class="site-btn"
          :class="{ active: selectedSite === site }"
          @click="selectedSite = site"
        >
          {{ site }}
        </button>
      </div>
    </div>

    <!-- 证据类型 -->
    <div class="form-group">
      <label>证据类型</label>
      <div class="evidence-grid">
        <button
          v-for="ev in VALID_EVIDENCE"
          :key="ev"
          class="evidence-btn"
          :class="{ active: selectedEvidence === ev }"
          @click="selectedEvidence = ev"
        >
          {{ ev }}
        </button>
      </div>
    </div>

    <!-- 次要感染部位 -->
    <div class="form-group">
      <label>次要感染部位（可选）</label>
      <div class="site-grid">
        <button
          v-for="site in VALID_SITES"
          :key="'sec-' + site"
          class="site-btn secondary"
          :class="{ active: secondarySites.includes(site) }"
          @click="toggleSecondary(site)"
        >
          {{ site }}
        </button>
      </div>
    </div>

    <!-- 备注 -->
    <div class="form-group">
      <label>备注</label>
      <textarea v-model="notes" rows="2" placeholder="可选备注..."></textarea>
    </div>

    <!-- 提交按钮 -->
    <div class="actions">
      <button class="btn-save" @click="handleSave" :disabled="!selectedSite">
        保存
      </button>
      <button class="btn-cancel" @click="$emit('cancel')">取消</button>
    </div>

    <!-- 历史记录 -->
    <div class="history" v-if="existingSites.length > 0">
      <h4>历史记录</h4>
      <div v-for="record in existingSites" :key="record.exclusion_key" class="history-item">
        <span class="site">{{ record.infection_site }}</span>
        <span class="evidence" v-if="record.evidence_type">({{ record.evidence_type }})</span>
        <span class="time">{{ formatTime(record.eval_time) }}</span>
        <button class="btn-delete" @click="$emit('delete', record.exclusion_key)">删除</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { fetchInfectionSite } from '../api/index.js';

const VALID_SITES = [
  '肺部', '腹腔', '泌尿道', '血流', '皮肤软组织',
  '中枢神经系统', '心血管', '骨关节', '五官',
  '其他', '不明确',
];

const VALID_EVIDENCE = ['影像学', '实验室', '临床', '病理', '微生物学'];

const props = defineProps({
  pid: { type: String, required: true },
});

const emit = defineEmits(['save', 'cancel', 'delete']);

const selectedSite = ref('');
const selectedEvidence = ref('');
const secondarySites = ref([]);
const notes = ref('');
const existingSites = ref([]);

function toggleSecondary(site) {
  const idx = secondarySites.value.indexOf(site);
  if (idx >= 0) {
    secondarySites.value.splice(idx, 1);
  } else {
    secondarySites.value.push(site);
  }
}

async function loadExisting() {
  try {
    const res = await fetchInfectionSite(props.pid);
    existingSites.value = res.sites || [];
  } catch (e) {
    console.error('Failed to load infection sites:', e);
  }
}

function handleSave() {
  emit('save', {
    infection_site: selectedSite.value,
    evidence_type: selectedEvidence.value,
    secondary_sites: secondarySites.value,
    notes: notes.value,
  });
}

function formatTime(t) {
  if (!t) return '';
  return new Date(t).toLocaleString('zh-CN');
}

onMounted(loadExisting);
</script>

<style scoped>
.infection-site-selector {
  padding: 16px;
}

h4 {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
  color: #374151;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 500;
  color: #4b5563;
}

.site-grid,
.evidence-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.site-btn,
.evidence-btn {
  padding: 6px 12px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: white;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.site-btn:hover,
.evidence-btn:hover {
  border-color: #3b82f6;
  background: #eff6ff;
}

.site-btn.active,
.evidence-btn.active {
  border-color: #3b82f6;
  background: #3b82f6;
  color: white;
}

.site-btn.secondary.active {
  background: #10b981;
  border-color: #10b981;
}

textarea {
  width: 100%;
  padding: 8px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 13px;
  resize: vertical;
}

.actions {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.btn-save {
  padding: 8px 16px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
}

.btn-save:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-cancel {
  padding: 8px 16px;
  background: white;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
}

.history {
  border-top: 1px solid #e5e7eb;
  padding-top: 12px;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  background: #f9fafb;
  border-radius: 6px;
  margin-bottom: 6px;
  font-size: 13px;
}

.history-item .site {
  font-weight: 500;
}

.history-item .evidence {
  color: #6b7280;
}

.history-item .time {
  color: #9ca3af;
  font-size: 12px;
  margin-left: auto;
}

.btn-delete {
  padding: 4px 8px;
  background: #fee2e2;
  color: #991b1b;
  border: none;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
}
</style>
