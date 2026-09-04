<template>
  <div class="sofa-panel">
    <h4>SOFA 评分</h4>

    <!-- 版本切换 -->
    <div class="version-tabs">
      <button
        class="version-tab"
        :class="{ active: version === 'classic' }"
        @click="version = 'classic'"
      >
        经典 SOFA 1996
      </button>
      <button
        class="version-tab"
        :class="{ active: version === 'sofa2' }"
        @click="version = 'sofa2'"
      >
        SOFA-2 2025
      </button>
    </div>

    <!-- 总分 -->
    <div class="total-score" v-if="currentScore">
      <div class="score-value" :class="scoreClass">{{ currentScore.total }}</div>
      <div class="score-label">总分</div>
    </div>
    <div class="no-data" v-else>暂无评分数据</div>

    <!-- 各器官分值 -->
    <div class="components" v-if="currentScore">
      <div v-for="(value, organ) in currentScore.components" :key="organ" class="component">
        <span class="organ-name">{{ organLabels[organ] || organ }}</span>
        <div class="score-bar">
          <div class="bar-fill" :style="{ width: (value / 4 * 100) + '%' }" :class="barClass(value)"></div>
        </div>
        <span class="score-num">{{ value ?? '—' }}</span>
      </div>
    </div>

    <!-- 数据质量标志 -->
    <div class="flags" v-if="currentScore?.data_quality_flags?.length > 0">
      <h4>数据质量标志</h4>
      <div v-for="flag in currentScore.data_quality_flags" :key="flag" class="flag">
        ⚠️ {{ flag }}
      </div>
    </div>

    <!-- 影子比对 -->
    <div class="shadow-compare" v-if="classicScore && sofa2Score">
      <h4>版本比对</h4>
      <div class="compare-row">
        <span>经典 SOFA: {{ classicScore.total ?? '—' }}</span>
        <span class="delta" :class="{ positive: delta > 0, negative: delta < 0 }">
          {{ delta > 0 ? '+' : '' }}{{ delta ?? '—' }}
        </span>
        <span>SOFA-2: {{ sofa2Score.total ?? '—' }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue';

const props = defineProps({
  classicScore: { type: Object, default: null },
  sofa2Score: { type: Object, default: null },
});

const version = ref('classic');

const currentScore = computed(() => {
  return version.value === 'classic' ? props.classicScore : props.sofa2Score;
});

const delta = computed(() => {
  if (!props.classicScore?.total || !props.sofa2Score?.total) return null;
  return props.sofa2Score.total - props.classicScore.total;
});

const scoreClass = computed(() => {
  const score = currentScore.value?.total;
  if (score == null) return '';
  if (score <= 6) return 'score-low';
  if (score <= 12) return 'score-mid';
  return 'score-high';
});

const organLabels = {
  respiratory: '呼吸',
  coagulation: '凝血',
  liver: '肝脏',
  cardiovascular: '心血管',
  central_nervous_system: '中枢神经',
  renal: '肾脏',
};

function barClass(value) {
  if (value == null) return '';
  if (value <= 1) return 'bar-low';
  if (value <= 2) return 'bar-mid';
  return 'bar-high';
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
}

.version-tab.active {
  border-color: #3b82f6;
  background: #3b82f6;
  color: white;
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

.no-data {
  text-align: center;
  padding: 24px;
  color: #9ca3af;
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

.score-num {
  width: 24px;
  text-align: right;
  font-size: 13px;
  font-weight: 600;
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
</style>
