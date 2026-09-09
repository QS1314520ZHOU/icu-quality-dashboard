<template>
  <div class="sofa-panel">
    <h4>SOFA 评分</h4>

    <!-- 版本切换 -->
    <div class="version-tabs">
      <button
        class="version-tab"
        :class="{ active: version === 'sofa2' }"
        @click="version = 'sofa2'"
      >
        SOFA-2 2025 (主)
      </button>
      <button
        class="version-tab"
        :class="{ active: version === 'classic' }"
        @click="version = 'classic'"
      >
        经典 SOFA 1996 (对照)
      </button>
    </div>

    <!-- 评分状态提示 -->
    <div class="status-bar" v-if="currentScore">
      <span class="status-badge" :class="statusClass">{{ statusLabel }}</span>
      <span class="completeness" v-if="currentScore.completeness != null">
        完整度: {{ Math.round(currentScore.completeness * 100) }}%
      </span>
    </div>

    <!-- 总分 -->
    <div class="total-score" v-if="currentScore && currentScoreTotal != null">
      <div class="score-value" :class="scoreClass">{{ currentScoreTotal }}</div>
      <div class="score-label">总分</div>
      <div class="score-hint" v-if="currentScore.result_status === 'partial'">
        ⚠️ 部分分项缺失，总分为已测分项之和
      </div>
    </div>
    <div class="no-data" v-else-if="!currentScore">暂无评分数据</div>
    <div class="no-data" v-else>
      <span>评分数据不足</span>
      <span class="missing-hint">缺少关键观测数据，无法计算总分</span>
    </div>

    <!-- 各器官分值 -->
    <div class="components" v-if="currentScore && currentScoreTotal != null">
      <div v-for="(value, organ) in currentScore.components" :key="organ" class="component">
        <span class="organ-name">{{ organLabels[organ] || organ }}</span>
        <div class="score-bar">
          <div
            class="bar-fill"
            :style="{ width: (value != null ? value / 4 * 100 : 0) + '%' }"
            :class="barClass(value)"
          ></div>
        </div>
        <span class="score-num" :class="{ missing: value == null }">
          {{ value != null ? value : '—' }}
        </span>
      </div>
    </div>

    <!-- 评估信息 -->
    <div class="eval-info" v-if="sofaData">
      <div class="eval-row" v-if="sofaData.eval_time">
        <span class="eval-label">评估时间:</span>
        <span class="eval-value">{{ formatTime(sofaData.eval_time) }}</span>
      </div>
      <div class="eval-row" v-if="sofaData.t0">
        <span class="eval-label">T0:</span>
        <span class="eval-value">{{ formatTime(sofaData.t0) }}</span>
      </div>
      <div class="eval-row" v-if="versionMeta">
        <span class="eval-label">评分版本:</span>
        <span class="eval-value">{{ versionMeta.rulepack_version }}</span>
        <span class="version-status" :class="versionMeta.lifecycle_status">
          {{ versionMeta.lifecycle_status === 'experimental' ? '实验性' : versionMeta.lifecycle_status }}
        </span>
      </div>
    </div>

    <!-- 数据质量标志 -->
    <div class="flags" v-if="currentQualityFlags.length > 0">
      <h4>数据质量标志</h4>
      <div v-for="flag in currentQualityFlags" :key="flag" class="flag">
        ⚠️ {{ flag }}
      </div>
    </div>

    <!-- 影子比对 -->
    <div class="shadow-compare" v-if="classicScore && sofa2Score">
      <h4>版本比对</h4>
      <div class="compare-row">
        <span>经典 SOFA: {{ classicScore.sofa_score ?? '—' }}</span>
        <span class="delta" :class="{ positive: delta > 0, negative: delta < 0 }">
          {{ delta != null ? (delta > 0 ? '+' : '') + delta : '—' }}
        </span>
        <span>SOFA-2: {{ sofa2Score.sofa2_score ?? '—' }}</span>
      </div>
    </div>

    <!-- 临床识别层 (如果有) -->
    <div class="clinical-layer" v-if="clinicalLayer">
      <h4>临床识别层</h4>

      <!-- 感染证据 -->
      <div class="layer-section">
        <div class="layer-title">
          <span>🦠 感染证据</span>
          <span class="layer-status" :class="{ confirmed: clinicalLayer.infection?.has_infection }">
            {{ clinicalLayer.infection?.has_infection ? '已确认' : '未确认' }}
          </span>
        </div>
      </div>

      <!-- 器官功能障碍 -->
      <div class="layer-section">
        <div class="layer-title">
          <span>🫀 急性器官功能障碍</span>
          <span class="layer-status" :class="{ confirmed: clinicalLayer.organ_dysfunction?.has_acute_organ_dysfunction }">
            {{ organDysLabel }}
          </span>
        </div>
        <div class="layer-detail" v-if="clinicalLayer.organ_dysfunction">
          <span>SOFA-2 总分: {{ clinicalLayer.organ_dysfunction.sofa2_total ?? '—' }}</span>
          <span class="basis">({{ clinicalLayer.organ_dysfunction.organ_dysfunction_basis }})</span>
        </div>
      </div>

      <!-- 脓毒症 -->
      <div class="layer-section">
        <div class="layer-title">
          <span>🔬 脓毒症</span>
          <span class="layer-status" :class="{
            confirmed: clinicalLayer.sepsis?.is_sepsis === true,
            negative: clinicalLayer.sepsis?.is_sepsis === false
          }">
            {{ sepsisLabel }}
          </span>
        </div>
      </div>

      <!-- 脓毒性休克 -->
      <div class="layer-section">
        <div class="layer-title">
          <span>💉 脓毒性休克</span>
          <span class="layer-status" :class="shockStatusClass">
            {{ shockStatusLabel }}
          </span>
        </div>
        <div class="layer-detail" v-if="clinicalLayer.shock?.lactate_borderline">
          ⚠️ 乳酸恰好 2.0 mmol/L，边界值
        </div>
        <div class="layer-detail" v-if="clinicalLayer.shock?.map_recovered">
          ℹ️ MAP 已恢复但仍依赖升压药
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue';

const props = defineProps({
  classicScore: { type: Object, default: null },
  sofa2Score: { type: Object, default: null },
  sofaData: { type: Object, default: null },  // 完整 sofa 数据 (含 version_meta)
  clinicalLayer: { type: Object, default: null },  // 临床识别层
});

const version = ref('sofa2');  // 默认 SOFA-2

const currentScore = computed(() => {
  return version.value === 'classic' ? props.classicScore : props.sofa2Score;
});

const currentScoreTotal = computed(() => {
  if (!currentScore.value) return null;
  return version.value === 'classic'
    ? currentScore.value.sofa_score
    : currentScore.value.sofa2_score;
});

const currentQualityFlags = computed(() => {
  if (!currentScore.value) return [];
  return currentScore.value.data_quality_flags || [];
});

const versionMeta = computed(() => {
  if (!props.sofaData?.version_meta) return null;
  return version.value === 'classic'
    ? props.sofaData.version_meta.classic
    : props.sofaData.version_meta.sofa2;
});

const delta = computed(() => {
  const c = props.classicScore?.sofa_score;
  const s = props.sofa2Score?.sofa2_score;
  if (c == null || s == null) return null;
  return s - c;
});

// 临床识别层标签
const organDysLabel = computed(() => {
  const v = props.clinicalLayer?.organ_dysfunction?.has_acute_organ_dysfunction;
  if (v === true) return '确认';
  if (v === false) return '未确认';
  return '数据不足';
});

const sepsisLabel = computed(() => {
  const v = props.clinicalLayer?.sepsis?.is_sepsis;
  if (v === true) return '确认';
  if (v === false) return '未确认';
  return '待判定';
});

const shockStatusLabel = computed(() => {
  const status = props.clinicalLayer?.shock?.shock_status;
  const labels = {
    confirmed: '确认',
    not_confirmed: '未确认',
    pending_review: '待复核',
    borderline: '边界值',
    insufficient_data: '数据不足',
  };
  return labels[status] || status || '—';
});

const shockStatusClass = computed(() => {
  const status = props.clinicalLayer?.shock?.shock_status;
  return {
    confirmed: status === 'confirmed',
    negative: status === 'not_confirmed',
    pending: status === 'pending_review' || status === 'borderline',
    insufficient: status === 'insufficient_data',
  };
});

// 样式计算
const statusClass = computed(() => {
  const s = currentScore.value?.result_status;
  if (s === 'complete') return 'status-complete';
  if (s === 'partial') return 'status-partial';
  return 'status-insufficient';
});

const statusLabel = computed(() => {
  const s = currentScore.value?.result_status;
  if (s === 'complete') return '完整';
  if (s === 'partial') return '部分';
  return '不足';
});

const scoreClass = computed(() => {
  const score = currentScoreTotal.value;
  if (score == null) return '';
  if (score <= 6) return 'score-low';
  if (score <= 12) return 'score-mid';
  return 'score-high';
});

const organLabels = {
  // 经典 SOFA
  respiratory: '呼吸',
  coagulation: '凝血',
  liver: '肝脏',
  cardiovascular: '心血管',
  central_nervous_system: '中枢神经',
  renal: '肾脏',
  // SOFA-2
  hemostasis: '止血',
  brain: '脑',
  kidney: '肾脏',
};

function barClass(value) {
  if (value == null) return 'bar-missing';
  if (value <= 1) return 'bar-low';
  if (value <= 2) return 'bar-mid';
  return 'bar-high';
}

function formatTime(ts) {
  if (!ts) return '';
  if (typeof ts === 'string') return ts.slice(0, 16);
  if (ts instanceof Date) return ts.toISOString().slice(0, 16);
  return String(ts).slice(0, 16);
}
</script>

<style scoped>
.sofa-panel {
  padding: 16px;
}

h4 {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
  color: #374151;
}

.version-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.version-tab {
  flex: 1;
  padding: 8px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: white;
  font-size: 13px;
  cursor: pointer;
  text-align: center;
  transition: all 0.2s;
}

.version-tab.active {
  border-color: #3b82f6;
  background: #3b82f6;
  color: white;
}

.status-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.status-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
}

.status-complete { background: #d1fae5; color: #065f46; }
.status-partial { background: #fef3c7; color: #92400e; }
.status-insufficient { background: #fee2e2; color: #991b1b; }

.completeness {
  font-size: 12px;
  color: #6b7280;
}

.total-score {
  text-align: center;
  margin-bottom: 16px;
}

.score-value {
  font-size: 48px;
  font-weight: 700;
  line-height: 1;
}

.score-low { color: #059669; }
.score-mid { color: #d97706; }
.score-high { color: #dc2626; }

.score-label {
  font-size: 14px;
  color: #6b7280;
  margin-top: 4px;
}

.score-hint {
  font-size: 12px;
  color: #92400e;
  margin-top: 4px;
}

.no-data {
  text-align: center;
  padding: 24px;
  color: #9ca3af;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.missing-hint {
  font-size: 12px;
}

.components {
  margin-bottom: 16px;
}

.component {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.organ-name {
  width: 80px;
  font-size: 13px;
  color: #4b5563;
}

.score-bar {
  flex: 1;
  height: 8px;
  background: #e5e7eb;
  border-radius: 4px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s;
}

.bar-low { background: #10b981; }
.bar-mid { background: #f59e0b; }
.bar-high { background: #ef4444; }
.bar-missing { background: #e5e7eb; }

.score-num {
  width: 24px;
  text-align: right;
  font-size: 13px;
  font-weight: 600;
}

.score-num.missing {
  color: #9ca3af;
  font-weight: 400;
}

.eval-info {
  margin-bottom: 16px;
  padding: 12px;
  background: #f9fafb;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
}

.eval-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  font-size: 13px;
}

.eval-row:last-child {
  margin-bottom: 0;
}

.eval-label {
  color: #6b7280;
  width: 80px;
}

.eval-value {
  color: #374151;
}

.version-status {
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
}

.version-status.experimental {
  background: #fef3c7;
  color: #92400e;
}

.version-status.approved {
  background: #d1fae5;
  color: #065f46;
}

.flags {
  margin-bottom: 16px;
  padding: 12px;
  background: #fef3c7;
  border-radius: 6px;
}

.flags h4 {
  margin: 0 0 8px;
  font-size: 13px;
  color: #92400e;
}

.flag {
  font-size: 12px;
  color: #92400e;
  margin-bottom: 4px;
}

.shadow-compare {
  padding: 12px;
  background: #f3f4f6;
  border-radius: 6px;
  margin-bottom: 16px;
}

.compare-row {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 12px;
  font-size: 14px;
}

.delta {
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}

.delta.positive {
  background: #fee2e2;
  color: #dc2626;
}

.delta.negative {
  background: #d1fae5;
  color: #059669;
}

/* 临床识别层 */
.clinical-layer {
  padding: 12px;
  background: #f0f9ff;
  border-radius: 6px;
  border: 1px solid #bae6fd;
}

.clinical-layer h4 {
  color: #0c4a6e;
  margin-bottom: 12px;
}

.layer-section {
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e0f2fe;
}

.layer-section:last-child {
  margin-bottom: 0;
  padding-bottom: 0;
  border-bottom: none;
}

.layer-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 500;
  color: #1e3a5f;
}

.layer-status {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  background: #e5e7eb;
  color: #6b7280;
}

.layer-status.confirmed {
  background: #fee2e2;
  color: #991b1b;
}

.layer-status.negative {
  background: #d1fae5;
  color: #065f46;
}

.layer-status.pending {
  background: #fef3c7;
  color: #92400e;
}

.layer-status.insufficient {
  background: #e5e7eb;
  color: #6b7280;
}

.layer-detail {
  margin-top: 4px;
  font-size: 12px;
  color: #6b7280;
}

.basis {
  color: #9ca3af;
  font-size: 11px;
}
</style>
