<template>
  <div class="bundle-detail">
    <!-- 患者基本信息 -->
    <div class="info-card">
      <div class="info-header">
        <span class="info-icon">👤</span>
        <span class="info-name">{{ patient.name || '—' }}</span>
        <span class="info-mrn">住院号: {{ patient.patient_id || '—' }}</span>
        <span class="info-type" v-if="patient.admission_type">入科类型: {{ patient.admission_type }}</span>
      </div>
      <div class="info-row">
        <span class="info-label">📋 入科诊断:</span>
        <span class="info-value">{{ patient.diagnose || '—' }}</span>
      </div>
      <div class="info-row">
        <span class="info-label">⏱️ T0:</span>
        <span class="info-value">{{ data.t0 || patient.t0 || patient.admit_time || '—' }}</span>
        <span class="info-hint">(首条医嘱时间)</span>
      </div>
    </div>

    <!-- 感染部位选择 -->
    <div class="infection-site-card">
      <div class="card-title" @click="showInfectionSite = !showInfectionSite">
        <span>🦠 感染部位确认</span>
        <span class="guide-toggle">{{ showInfectionSite ? '▼' : '▶' }}</span>
      </div>
      <InfectionSiteSelector v-if="showInfectionSite" :pid="patient.sc_pid || patient.patient_id || ''" />
    </div>

    <!-- ====== 分母详情：如何判定为脓毒性休克 ====== -->
    <template v-if="part === 'denominator'">
      <!-- K组 - 脓毒性休克确认 -->
      <div class="group-card">
        <div class="card-title">🩺 脓毒性休克确认 (K1 AND K2)</div>
        <div class="group-items">
          <div class="group-item">
            <span class="item-label">K1 血乳酸 ≥2 mmol/L</span>
            <StatusBadge :value="data.k1" />
            <span class="item-detail" v-if="data.lactate != null">{{ fmtNum(data.lactate) }} mmol/L {{ data.lactate_time ? `@${data.lactate_time}` : '' }}</span>
            <span class="item-detail" v-else>未测量</span>
          </div>
          <div class="group-item">
            <span class="item-label">K2 升压药使用</span>
            <StatusBadge :value="data.k2" />
            <span class="item-detail" v-if="data.vaso_name">{{ data.vaso_name }} @{{ data.vaso_start_time || '—' }}</span>
            <span class="item-detail" v-else>未使用</span>
          </div>
        </div>
        <div class="group-result">
          <span class="result-label">→ 脓毒性休克确认</span>
          <StatusBadge :value="data.is_septic_shock" />
        </div>
      </div>

      <!-- I组 - 感染证据 -->
      <div class="group-card">
        <div class="card-title">🦠 感染证据 (I1 ∨ I2 ∨ I3 任一成立)</div>
        <div class="group-items">
          <div class="group-item">
            <span class="item-label">I1 诊断含感染关键词</span>
            <StatusBadge :value="data.i1" />
            <span class="item-detail">{{ truncate(patient.diagnose, 30) || '—' }}</span>
          </div>
          <div class="group-item">
            <span class="item-label">I2 抗感染治疗执行</span>
            <StatusBadge :value="data.i2" />
            <span class="item-detail" v-if="data.antibiotic_name">{{ data.antibiotic_name }} @{{ data.antibiotic_time || '—' }}</span>
            <span class="item-detail" v-else>未执行</span>
          </div>
          <div class="group-item">
            <span class="item-label">I3 病原学送检</span>
            <StatusBadge :value="data.i3" />
            <span class="item-detail" v-if="data.culture_time">{{ data.culture_name }} @{{ data.culture_time }}</span>
            <span class="item-detail" v-else>未送检</span>
          </div>
        </div>
        <div class="group-result">
          <span class="result-label">→ 感染证据确认</span>
          <StatusBadge :value="data.i1 || data.i2 || data.i3" />
        </div>
      </div>

      <!-- S组 - 器官功能障碍 -->
      <div class="group-card">
        <div class="card-title">🫀 器官功能障碍 (S1∨S2∨S3∨S4 任一成立)</div>
        <div class="group-items">
          <div class="group-item">
            <span class="item-label">S1 氧合指数 &lt;300</span>
            <StatusBadge :value="data.s1" />
            <span class="item-detail" v-if="data.pf_ratio != null">{{ data.pf_ratio }} {{ data.pf_ratio_time ? `@${data.pf_ratio_time}` : '' }}</span>
            <span class="item-detail" v-else>未测量</span>
          </div>
          <div class="group-item">
            <span class="item-label">S2 GCS &lt;13</span>
            <StatusBadge :value="data.s2" />
            <span class="item-detail" v-if="data.gcs != null">{{ data.gcs }}分 {{ data.gcs_time ? `@${data.gcs_time}` : '' }}</span>
            <span class="item-detail" v-else>未测量</span>
          </div>
          <div class="group-item">
            <span class="item-label">S3 MAP &lt;70 mmHg</span>
            <StatusBadge :value="data.s3" />
            <span class="item-detail" v-if="data.map != null">{{ data.map }} mmHg {{ data.map_time ? `@${data.map_time}` : '' }}</span>
            <span class="item-detail" v-else>未测量</span>
          </div>
          <div class="group-item">
            <span class="item-label">S4 血管活性药</span>
            <StatusBadge :value="data.s4" />
            <span class="item-detail" v-if="data.vaso_name">{{ data.vaso_name }}</span>
            <span class="item-detail" v-else>未使用</span>
          </div>
        </div>
        <div class="group-result">
          <span class="result-label">→ 器官功能障碍</span>
          <StatusBadge :value="data.s1 || data.s2 || data.s3 || data.s4" />
        </div>
      </div>
    </template>

    <!-- ====== 分子详情：Bundle 执行情况 ====== -->
    <template v-if="part === 'numerator'">
      <!-- Bundle 时间线 -->
      <div class="timeline-card">
        <div class="card-title">⏱️ Bundle 时间线</div>
        <div class="timeline">
          <div class="timeline-item active">
            <div class="timeline-dot"></div>
            <div class="timeline-content">
              <div class="timeline-label">T0</div>
              <div class="timeline-value">{{ formatTime(data.t0 || patient.t0) }}</div>
            </div>
          </div>
          <div class="timeline-line"></div>
          <div class="timeline-item" :class="{ active: data.lactate != null }">
            <div class="timeline-dot" :class="statusClass(data.a1)"></div>
            <div class="timeline-content">
              <div class="timeline-label">乳酸</div>
              <div class="timeline-value">{{ data.lactate != null ? `${fmtNum(data.lactate)} mmol/L` : '—' }}</div>
              <div class="timeline-time" v-if="data.lactate_time">{{ data.lactate_time }}</div>
            </div>
          </div>
          <div class="timeline-line"></div>
          <div class="timeline-item" :class="{ active: !!data.culture_time }">
            <div class="timeline-dot" :class="statusClass(!!data.culture_time && !!data.antibiotic_time && data.culture_time < data.antibiotic_time)"></div>
            <div class="timeline-content">
              <div class="timeline-label">血培养</div>
              <div class="timeline-value">{{ data.culture_name || '—' }}</div>
              <div class="timeline-time" v-if="data.culture_time">{{ data.culture_time }}</div>
            </div>
          </div>
          <div class="timeline-line"></div>
          <div class="timeline-item" :class="{ active: !!data.antibiotic_time }">
            <div class="timeline-dot" :class="statusClass(!!data.antibiotic_time)"></div>
            <div class="timeline-content">
              <div class="timeline-label">抗生素</div>
              <div class="timeline-value">{{ data.antibiotic_name || '—' }}</div>
              <div class="timeline-time" v-if="data.antibiotic_time">{{ data.antibiotic_time }}</div>
            </div>
          </div>
          <div class="timeline-line"></div>
          <div class="timeline-item" :class="{ active: (data.fluid_ml || 0) > 0 }">
            <div class="timeline-dot" :class="statusClass(data.c3)"></div>
            <div class="timeline-content">
              <div class="timeline-label">液体</div>
              <div class="timeline-value">{{ data.fluid_ml ? `${data.fluid_ml} ml` : '—' }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Bundle 完成情况 -->
      <div class="group-card">
        <div class="card-title">📦 Bundle 完成判定</div>
        <div class="group-items">
          <div class="group-item">
            <span class="item-label">第一步 A1 乳酸测定</span>
            <StatusBadge :value="data.a1" />
            <span class="item-detail" v-if="data.lactate != null">{{ fmtNum(data.lactate) }} mmol/L {{ data.lactate_time ? `@${data.lactate_time}` : '' }}</span>
            <span class="item-detail" v-else>未测量</span>
          </div>
          <div class="group-item">
            <span class="item-label">第二步 B3 血培养先于抗生素</span>
            <StatusBadge :value="data.b3" />
            <span class="item-detail" v-if="data.culture_time && data.antibiotic_time">
              培养@{{ data.culture_time }} &lt; 抗生素@{{ data.antibiotic_time }}
            </span>
            <span class="item-detail" v-else>数据不完整</span>
          </div>
          <div class="group-item">
            <span class="item-label">第三步 C1 MAP&lt;70 触发</span>
            <StatusBadge :value="data.c1" />
            <span class="item-detail" v-if="data.map != null">{{ data.map }} mmHg</span>
            <span class="item-detail" v-else>未测量</span>
          </div>
          <div class="group-item">
            <span class="item-label">第三步 C2 乳酸≥4 触发</span>
            <StatusBadge :value="data.c2" />
            <span class="item-detail" v-if="data.lactate_max != null">{{ fmtNum(data.lactate_max) }} mmol/L</span>
            <span class="item-detail" v-else>未测量</span>
          </div>
          <div class="group-item">
            <span class="item-label">第三步 C3 液体达标</span>
            <StatusBadge :value="data.c3" />
            <span class="item-detail" v-if="data.fluid_ml">{{ data.fluid_ml }} ml</span>
            <span class="item-detail" v-else>无液体</span>
          </div>
        </div>
        <div class="group-result">
          <span class="result-label">→ Bundle 完成</span>
          <StatusBadge :value="data.finish" />
          <span class="result-path" v-if="data.finish">完成路径: {{ data.finish_path || '—' }}</span>
        </div>
      </div>
    </template>

    <!-- 原因码展示 -->
    <div class="reason-card" v-if="data.reason">
      <div class="card-title">ℹ️ 判定说明</div>
      <div class="reason-list">
        <div class="reason-item">
          <span class="reason-code">{{ data.reason }}</span>
          <span class="reason-text">{{ reasonText }}</span>
        </div>
      </div>
    </div>

    <!-- 数据质量标记 -->
    <div class="quality-card" v-if="data.data_quality_flags && data.data_quality_flags.length > 0">
      <div class="card-title">⚠️ 数据质量标记</div>
      <div class="quality-list">
        <div class="quality-item" v-for="flag in data.data_quality_flags" :key="flag">
          {{ flag }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import StatusBadge from './StatusBadge.vue'
import InfectionSiteSelector from './InfectionSiteSelector.vue'

const props = defineProps({
  data: { type: Object, default: () => ({}) },
  patient: { type: Object, default: () => ({}) },
  part: { type: String, default: 'denominator' }, // 'denominator' | 'numerator'
})

const showInfectionSite = ref(false)

const REASON_MAP = {
  'NO_T0': '找不到T0锚点',
  'NOT_SEPTIC_SHOCK': '非脓毒性休克 (K1/K2未确认)',
  'NO_INFECTION_EVIDENCE': '无感染证据 (I1/I2/I3均未确认)',
  'A1_NOT_MET': 'A1未达标: 乳酸未测量',
  'B3_NOT_MET': 'B3未达标: 抗生素未在血培养后使用',
  'C3_FLUID_INSUFFICIENT': 'C3未达标: 液体量不足',
  'MAP_NOT_TRIGGERED': 'MAP未触发 (<70mmHg)',
  'LACTATE_NOT_TRIGGERED': '乳酸未触发 (<4mmol/L)',
  'FINISH_FALSE': 'Bundle未完成',
  'DATA_MISSING_LAC': '乳酸数据缺失',
  'DATA_MISSING_MAP': 'MAP数据缺失',
  'AB_MISSING': '找不到抗菌药物执行记录',
  'BC_MISSING': '找不到血培养记录',
  'FLUID_NONE': '窗口内无液体执行',
  'FLUID_INSUFFICIENT': '液体量不足1500ml',
  'SITE_UNCONFIRMED': '感染部位未人工确认',
  'MANUAL_EXCLUDED': '人工排除',
}

const reasonText = computed(() => {
  return REASON_MAP[props.data.reason] || props.data.reason || ''
})

function fmtNum(val) {
  if (val == null) return '—'
  return Number(val).toFixed(2)
}

function formatTime(t) {
  if (!t) return '—'
  if (typeof t === 'string') return t.slice(5)
  return String(t)
}

function truncate(str, len) {
  if (!str) return ''
  return str.length > len ? str.slice(0, len) + '...' : str
}

function statusClass(value) {
  if (value === true) return 'status-ok'
  if (value === false) return 'status-fail'
  return 'status-na'
}
</script>

<style scoped>
.bundle-detail {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  background: var(--bg-subtle);
  border-radius: 8px;
}

.info-card, .timeline-card, .group-card, .reason-card, .quality-card, .infection-site-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
}

.info-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.info-icon { font-size: 1.2em; }
.info-name { font-weight: 600; color: var(--text-title); font-size: 1.1em; }
.info-mrn { color: var(--text-sub); font-family: monospace; }
.info-type { background: var(--brand-weak); color: var(--brand); padding: 2px 8px; border-radius: 4px; font-size: 0.85em; }

.info-row { display: flex; align-items: baseline; gap: 8px; margin-top: 4px; font-size: 0.9em; }
.info-label { color: var(--text-sub); white-space: nowrap; }
.info-value { color: var(--text-body); }
.info-hint { color: var(--text-sub); font-size: 0.85em; }

.card-title { font-weight: 600; color: var(--text-title); margin-bottom: 12px; font-size: 0.95em; }

/* Timeline */
.timeline { display: flex; align-items: flex-start; gap: 0; overflow-x: auto; padding: 8px 0; }
.timeline-item { display: flex; flex-direction: column; align-items: center; min-width: 100px; opacity: 0.4; }
.timeline-item.active { opacity: 1; }
.timeline-dot { width: 12px; height: 12px; border-radius: 50%; background: var(--border); margin-bottom: 8px; }
.timeline-dot.status-ok { background: var(--success, #10b981); }
.timeline-dot.status-fail { background: var(--danger, #ef4444); }
.timeline-dot.status-na { background: var(--border); }
.timeline-line { flex: 1; height: 2px; background: var(--border); margin-top: 5px; min-width: 20px; }
.timeline-content { text-align: center; }
.timeline-label { font-weight: 600; color: var(--text-sub); font-size: 0.8em; margin-bottom: 4px; }
.timeline-value { color: var(--text-body); font-size: 0.85em; white-space: nowrap; }
.timeline-time { color: var(--text-sub); font-size: 0.75em; }

/* Group items */
.group-items { display: flex; flex-direction: column; gap: 8px; }
.group-item { display: flex; align-items: center; gap: 12px; padding: 6px 0; border-bottom: 1px solid var(--border-light); }
.group-item:last-child { border-bottom: none; }
.item-label { min-width: 180px; color: var(--text-sub); font-size: 0.9em; }
.item-detail { color: var(--text-body); font-size: 0.85em; flex: 1; }

.group-result { display: flex; align-items: center; gap: 12px; margin-top: 12px; padding-top: 12px; border-top: 2px solid var(--border); }
.result-label { font-weight: 600; color: var(--text-title); }
.result-path { color: var(--text-sub); font-size: 0.85em; margin-left: 8px; }

/* Reason */
.reason-list { display: flex; flex-direction: column; gap: 8px; }
.reason-item { display: flex; align-items: center; gap: 12px; }
.reason-code { background: var(--bg-subtle); color: var(--text-sub); padding: 2px 8px; border-radius: 4px; font-family: monospace; font-size: 0.85em; }
.reason-text { color: var(--text-body); font-size: 0.9em; }

/* Quality */
.quality-list { display: flex; flex-direction: column; gap: 4px; }
.quality-item { color: var(--warn, #f59e0b); font-size: 0.85em; }

.infection-site-card .card-title { cursor: pointer; display: flex; justify-content: space-between; align-items: center; margin-bottom: 0; }
.guide-toggle { color: var(--text-sub); font-size: 0.85em; }
</style>
