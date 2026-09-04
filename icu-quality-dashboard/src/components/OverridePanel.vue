<template>
  <div class="override-panel">
    <h4>三层人工覆盖</h4>

    <!-- 覆盖层级选择 -->
    <div class="form-group">
      <label>覆盖层级</label>
      <div class="level-tabs">
        <button
          v-for="level in LEVELS"
          :key="level.value"
          class="level-tab"
          :class="{ active: selectedLevel === level.value }"
          @click="selectedLevel = level.value"
        >
          {{ level.label }}
        </button>
      </div>
    </div>

    <!-- 指标选择 (L2/L3) -->
    <div class="form-group" v-if="selectedLevel !== 'L1'">
      <label>指标</label>
      <select v-model="selectedIndicator">
        <option value="">请选择指标</option>
        <option v-for="ind in INDICATORS" :key="ind.code" :value="ind.code">
          {{ ind.name }}
        </option>
      </select>
    </div>

    <!-- 覆盖值 -->
    <div class="form-group">
      <label>覆盖值</label>
      <div class="value-options">
        <button
          class="value-btn"
          :class="{ active: overrideValue === true }"
          @click="overrideValue = true"
        >
          ✅ 达标
        </button>
        <button
          class="value-btn"
          :class="{ active: overrideValue === false }"
          @click="overrideValue = false"
        >
          ❌ 未达标
        </button>
        <button
          class="value-btn"
          :class="{ active: overrideValue === null }"
          @click="overrideValue = null"
        >
          ⚠️ 缺失
        </button>
      </div>
    </div>

    <!-- 原因码 -->
    <div class="form-group">
      <label>原因码</label>
      <select v-model="selectedReason">
        <option value="">请选择原因</option>
        <optgroup v-for="(reasons, category) in REASON_CODES" :key="category" :label="category">
          <option v-for="(text, code) in reasons" :key="code" :value="category + '.' + code">
            {{ text }}
          </option>
        </optgroup>
      </select>
    </div>

    <!-- 备注 -->
    <div class="form-group">
      <label>备注</label>
      <textarea v-model="reasonText" rows="2" placeholder="可选备注..."></textarea>
    </div>

    <!-- 操作者 -->
    <div class="form-group">
      <label>操作者</label>
      <input v-model="operator" placeholder="操作者姓名" />
    </div>

    <!-- 提交按钮 -->
    <div class="actions">
      <button class="btn-save" @click="handleSave" :disabled="!canSave">
        保存覆盖
      </button>
      <button class="btn-cancel" @click="$emit('cancel')">取消</button>
    </div>

    <!-- 历史覆盖记录 -->
    <div class="history" v-if="existingOverrides.length > 0">
      <h4>历史覆盖记录</h4>
      <div v-for="record in existingOverrides" :key="record.override_key" class="history-item">
        <span class="level">{{ record.level }}</span>
        <span class="indicator" v-if="record.indicator_id">{{ record.indicator_id }}</span>
        <span class="value" :class="{ 'value-true': record.override_value === true, 'value-false': record.override_value === false }">
          {{ record.override_value === true ? '达标' : record.override_value === false ? '未达标' : '缺失' }}
        </span>
        <span class="reason">{{ record.reason_code }}</span>
        <span class="time">{{ formatTime(record.created_at) }}</span>
        <button class="btn-delete" @click="$emit('delete', record.override_key)">删除</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import { fetchBundleOverrides } from '../api/index.js';

const LEVELS = [
  { value: 'L1', label: 'L1 患者级' },
  { value: 'L2', label: 'L2 指标级' },
  { value: 'L3', label: 'L3 组件级' },
];

const INDICATORS = [
  { code: 'ICU-05-1h', name: '感染性休克1h Bundle' },
  { code: 'ICU-05-3h', name: '感染性休克3h Bundle' },
  { code: 'ICU-05-6h', name: '感染性休克6h Bundle' },
];

const REASON_CODES = {
  bundle_judgment: {
    not_septic_shock: '非脓毒性休克',
    no_infection_evidence: '无感染证据',
    a1_not_met: 'A1未达标: 乳酸未测量',
    b3_not_met: 'B3未达标: 抗生素未在血培养后使用',
    c3_fluid_insufficient: 'C3未达标: 液体量不足',
    finish_false: 'Bundle未完成',
  },
  data_quality: {
    missing_critical: '关键数据缺失',
    unit_mismatch: '单位不匹配',
    value_outlier: '数值异常',
  },
  clinical: {
    chronic_organ_dysfunction: '慢性器官功能障碍',
    contraindication: '治疗禁忌',
    patient_refusal: '患者/家属拒绝',
  },
  override: {
    clinical_judgment: '临床判断覆盖',
    quality_improvement: '质量改进排除',
    documentation_correction: '文书纠正',
  },
};

const props = defineProps({
  pid: { type: String, required: true },
  evalTime: { type: String, default: '' },
});

const emit = defineEmits(['save', 'cancel', 'delete']);

const selectedLevel = ref('L1');
const selectedIndicator = ref('');
const overrideValue = ref(null);
const selectedReason = ref('');
const reasonText = ref('');
const operator = ref('');
const existingOverrides = ref([]);

const canSave = computed(() => {
  if (!selectedReason.value) return false;
  if (selectedLevel.value !== 'L1' && !selectedIndicator.value) return false;
  return true;
});

async function loadExisting() {
  try {
    const res = await fetchBundleOverrides(props.pid);
    existingOverrides.value = res.overrides || [];
  } catch (e) {
    console.error('Failed to load overrides:', e);
  }
}

function handleSave() {
  emit('save', {
    level: selectedLevel.value,
    indicator_id: selectedLevel.value !== 'L1' ? selectedIndicator.value : null,
    override_value: overrideValue.value,
    reason_code: selectedReason.value,
    reason_text: reasonText.value,
    operator: operator.value || 'unknown',
    eval_time: props.evalTime,
  });
}

function formatTime(t) {
  if (!t) return '';
  return new Date(t).toLocaleString('zh-CN');
}

onMounted(loadExisting);
</script>

<style scoped>
.override-panel {
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

.level-tabs {
  display: flex;
  gap: 8px;
}

.level-tab {
  flex: 1;
  padding: 8px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: white;
  font-size: 13px;
  cursor: pointer;
  text-align: center;
}

.level-tab.active {
  border-color: #3b82f6;
  background: #3b82f6;
  color: white;
}

select {
  width: 100%;
  padding: 8px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 13px;
}

.value-options {
  display: flex;
  gap: 8px;
}

.value-btn {
  flex: 1;
  padding: 8px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: white;
  font-size: 13px;
  cursor: pointer;
}

.value-btn.active {
  border-color: #3b82f6;
  background: #eff6ff;
}

textarea,
input {
  width: 100%;
  padding: 8px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 13px;
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

.history-item .level {
  font-weight: 600;
  color: #3b82f6;
}

.history-item .indicator {
  color: #6b7280;
}

.history-item .value {
  font-weight: 500;
}

.value-true { color: #059669; }
.value-false { color: #dc2626; }

.history-item .reason {
  color: #9ca3af;
  font-size: 12px;
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
