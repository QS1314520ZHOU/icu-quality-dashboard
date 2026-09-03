<template>
  <div class="dashboard" :class="{ compact: compactMode }">
    <!-- 页面头：标题行 + 期间选择 + 状态 + 密度切换 -->
    <header class="db-header">
      <div class="db-header-left">
        <h1 class="db-title">实时大屏看板</h1>
        <span class="db-subtitle">统计期间 {{ periodLabel }}</span>
      </div>
      <div class="db-header-right">
        <nav class="anchor-nav">
          <a href="#sec-structure" class="anchor-link">结构</a>
          <a href="#sec-process" class="anchor-link">过程</a>
          <a href="#sec-outcome" class="anchor-link">结果</a>
          <a href="#sec-combo" class="anchor-link">组合</a>
          <a href="#sec-compare" class="anchor-link">对比表</a>
        </nav>
        <div class="period-selector">
          <span class="period-label">统计期间</span>
          <select v-model.number="year" @change="loadData">
            <option v-for="y in years" :key="y" :value="y">{{ y }}年</option>
          </select>
          <select v-model.number="sMonth" @change="loadData">
            <option v-for="m in 12" :key="m" :value="m">{{ m }}月</option>
          </select>
          <span class="period-to">至</span>
          <select v-model.number="eMonth" @change="loadData">
            <option v-for="m in 12" :key="m" :value="m">{{ m }}月</option>
          </select>
        </div>
        <button class="density-btn" @click="compactMode = !compactMode" :title="compactMode ? '切换舒适模式' : '切换紧凑模式'">
          <svg v-if="compactMode" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2 4h12M2 8h12M2 12h12"/></svg>
          <svg v-else viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 5h10M3 8h10M3 11h10"/></svg>
        </button>
        <span class="status-pill" :class="risk.overall_status">
          <svg class="pill-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="5"/></svg>
          数据状态 · {{ overallText }}
        </span>
        <span v-if="updatedAt" class="meta-update">最后更新 {{ updatedAt }}</span>
      </div>
    </header>

    <div v-if="error" class="state error">{{ error }}</div>
    <div v-else-if="loading" class="state loading">
      <svg class="spin-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M8 1v4M8 11v4M1 8h4M11 8h4M3.05 3.05l2.83 2.83M10.12 10.12l2.83 2.83M3.05 12.95l2.83-2.83M10.12 5.88l2.83-2.83"/></svg>
      正在读取预聚合质控数据...
    </div>

    <!-- KPI 条 6 张：数值 + DeltaBadge(环比、同比) + Sparkline -->
    <section class="kpi-stats">
      <div v-for="kpi in kpiCards" :key="kpi.code" class="kpi-stat-card" :class="kpi.status">
        <div class="kpi-card-left" :class="kpi.status"></div>
        <div class="kpi-card-body">
          <div class="kpi-card-top">
            <span class="kpi-card-label">{{ kpi.name }}</span>
            <span class="kpi-card-code">{{ displayCode(kpi.code) }}</span>
          </div>
          <div class="kpi-card-main">
            <strong class="kpi-card-big tabular-nums">{{ kpi.valueText }}</strong>
            <small class="kpi-card-unit">{{ kpi.unit }}</small>
          </div>
          <div class="kpi-card-deltas">
            <DeltaBadge
              :text="kpi.momText"
              :tooltip="kpi.momTooltip"
              :css-class="kpi.momClass"
              :arrow="kpi.momArrow"
              label="环比"
              :small-sample="kpi.momSmall"
            />
            <DeltaBadge
              :text="kpi.yoyText"
              :tooltip="kpi.yoyTooltip"
              :css-class="kpi.yoyClass"
              :arrow="kpi.yoyArrow"
              label="同比"
              :small-sample="kpi.yoySmall"
            />
          </div>
          <Sparkline :data="trendData[kpi.code] || []" :height="24" />
        </div>
      </div>
    </section>

    <!-- 异常指标清单 + AI 面板 -->
    <section class="abnormal-ai-strip">
      <div class="panel abnormal-panel">
        <div class="panel-title">
          <svg class="panel-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M8 1L15 14H1L8 1zM8 6v4M8 12h.01"/></svg>
          异常指标清单
          <span class="abnormal-count" v-if="abnormalList.length">{{ abnormalList.length }}</span>
        </div>
        <div v-if="abnormalList.length" class="abnormal-list">
          <div v-for="a in abnormalList" :key="a.code" class="abnormal-item" :class="a.status" @click="openDetail(a)">
            <div class="ab-main">
              <span class="ab-code">{{ displayCode(a.code) }}</span>
              <strong>{{ a.name }}</strong>
              <span class="ab-status">{{ statusText(a.status) }}</span>
            </div>
            <div class="ab-meta">
              当前 {{ fmtValue(a.value) }}{{ a.unit }} · 分子 {{ a.numerator ?? '/' }} / 分母 {{ a.denominator ?? '/' }}
            </div>
          </div>
        </div>
        <div v-else class="empty">
          <svg class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 12h6M12 9v6"/><circle cx="12" cy="12" r="10"/></svg>
          当前范围内暂无异常或预警指标
        </div>
      </div>
      <div class="panel ai-panel-wrap">
        <AiPanel :analysis="ai" />
      </div>
    </section>

    <!-- 结构指标区 -->
    <section id="sec-structure" class="zone-section">
      <div class="zone-title-bar">
        <h2 class="zone-title">
          <svg class="zone-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="2" width="5" height="12" rx="1"/><rect x="9" y="4" width="5" height="10" rx="1"/></svg>
          结构与资源
        </h2>
        <div class="zone-stats">
          <span class="zone-stat good" v-if="zoneStats.structure.good">{{ zoneStats.structure.good }} 项达标</span>
          <span class="zone-stat warn" v-if="zoneStats.structure.warn">{{ zoneStats.structure.warn }} 项预警</span>
          <span class="zone-stat danger" v-if="zoneStats.structure.danger">{{ zoneStats.structure.danger }} 项异常</span>
        </div>
      </div>
      <div class="zone-grid ring-grid">
        <div v-for="code in structureCodes" :key="code" class="zone-cell" @click="openDetail(rowsByCode[code])">
          <RingProgress
            :name="rowsByCode[code]?.name || code"
            :value="rowsByCode[code]?.value || 0"
            :unit="rowsByCode[code]?.unit || '%'"
            :status="rowsByCode[code]?.status || 'unknown'"
            :numerator-label="getIndicatorProp(code, 'numerator')"
            :numerator="rowsByCode[code]?.numerator"
            :denominator-label="getIndicatorProp(code, 'denominator')"
            :denominator="rowsByCode[code]?.denominator"
          />
        </div>
      </div>
    </section>

    <!-- 过程指标区 -->
    <section id="sec-process" class="zone-section">
      <div class="zone-title-bar">
        <h2 class="zone-title">
          <svg class="zone-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="6"/><path d="M8 4v4l3 2"/></svg>
          过程质量
        </h2>
        <div class="zone-stats">
          <span class="zone-stat good" v-if="zoneStats.process.good">{{ zoneStats.process.good }} 项达标</span>
          <span class="zone-stat warn" v-if="zoneStats.process.warn">{{ zoneStats.process.warn }} 项预警</span>
          <span class="zone-stat danger" v-if="zoneStats.process.danger">{{ zoneStats.process.danger }} 项异常</span>
        </div>
      </div>
      <!-- 一排 ring -->
      <div class="zone-grid ring-grid-wrap">
        <div v-for="code in processCodes" :key="code" class="zone-cell" @click="openDetail(rowsByCode[code])">
          <RingProgress
            :name="rowsByCode[code]?.name || code"
            :value="rowsByCode[code]?.value || 0"
            :unit="rowsByCode[code]?.unit || '%'"
            :status="rowsByCode[code]?.status || 'unknown'"
            :numerator-label="getIndicatorProp(code, 'numerator')"
            :numerator="rowsByCode[code]?.numerator"
            :denominator-label="getIndicatorProp(code, 'denominator')"
            :denominator="rowsByCode[code]?.denominator"
          />
        </div>
      </div>
      <!-- 下方 hbar 排行 -->
      <div class="zone-chart">
        <HBarRankChart
          :items="processHbarItems"
          unit="%"
          :height="220"
          @click="handleChartClick"
        />
      </div>
    </section>

    <!-- 结果指标区 -->
    <section id="sec-outcome" class="zone-section">
      <div class="zone-title-bar">
        <h2 class="zone-title">
          <svg class="zone-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="1,12 4,6 7,9 10,3 15,8"/><line x1="1" y1="14" x2="15" y2="14"/></svg>
          结果质量
        </h2>
        <div class="zone-stats">
          <span class="zone-stat good" v-if="zoneStats.outcome.good">{{ zoneStats.outcome.good }} 项达标</span>
          <span class="zone-stat warn" v-if="zoneStats.outcome.warn">{{ zoneStats.outcome.warn }} 项预警</span>
          <span class="zone-stat danger" v-if="zoneStats.outcome.danger">{{ zoneStats.outcome.danger }} 项异常</span>
        </div>
      </div>
      <div class="zone-chart">
        <HBarRankChart
          :items="outcomeHbarItems"
          unit="%"
          :height="260"
          @click="handleChartClick"
        />
      </div>
      <!-- SMR 专项 -->
      <div class="smr-row">
        <SmrChart :current="smrCurrent" :history="smrHistory" :months="months" />
      </div>
    </section>

    <!-- 组合视图区：2 列栅格 -->
    <section id="sec-combo" class="zone-section">
      <div class="zone-title-bar">
        <h2 class="zone-title">
          <svg class="zone-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="1" y="1" width="6" height="6" rx="1"/><rect x="9" y="1" width="6" height="6" rx="1"/><rect x="1" y="9" width="6" height="6" rx="1"/><rect x="9" y="9" width="6" height="6" rx="1"/></svg>
          组合分析
        </h2>
      </div>
      <div class="combo-grid">
        <!-- 感染防控组 -->
        <div class="panel combo-panel">
          <div class="panel-title">
            <svg class="panel-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M8 1v14M1 8h14"/><circle cx="8" cy="8" r="3"/></svg>
            感染防控
          </div>
          <GroupedBarChart
            :categories="infectionCategories"
            :series="infectionSeries"
            unit="‰"
            :height="260"
          />
        </div>

        <!-- Sepsis 漏斗 -->
        <div class="panel combo-panel">
          <div class="panel-title">
            <svg class="panel-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2 3h12L10 8H6L2 3zM4 8h8l-2 5H6L4 8z"/></svg>
            Sepsis Bundle
          </div>
          <FunnelBundleChart :data="bundleFunnelData" :height="260" />
        </div>

        <!-- 镇痛镇静雷达 -->
        <div class="panel combo-panel">
          <div class="panel-title">
            <svg class="panel-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><polygon points="8,1 14,5 14,11 8,15 2,11 2,5"/></svg>
            镇痛镇静意识评估
          </div>
          <RadarAssessChart :data="sedationRadarData" :height="260" />
        </div>

        <!-- 人力与负荷 -->
        <div class="panel combo-panel">
          <div class="panel-title">
            <svg class="panel-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 2v12M12 2v12M2 6h4M10 4h4M2 10h4M10 8h4"/></svg>
            人力与负荷
          </div>
          <BarTargetChart :items="ratioItems" />
        </div>

        <!-- 患者流转 -->
        <div class="panel combo-panel">
          <div class="panel-title">
            <svg class="panel-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2 4h12M2 8h12M2 12h12"/></svg>
            患者流转
          </div>
          <CensusStackChart :trend="censusTrend" />
        </div>

        <!-- 气道安全 -->
        <div class="panel combo-panel">
          <div class="panel-title">
            <svg class="panel-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M8 1v4M5 5l3 4 3-4M4 13h8M6 9v4M10 9v4"/></svg>
            气道安全
          </div>
          <GroupedBarChart
            :categories="airwayCategories"
            :series="airwaySeries"
            unit="%"
            :height="220"
          />
        </div>
      </div>
    </section>

    <!-- 环比同比总表 -->
    <section id="sec-compare" class="zone-section">
      <ComparisonTable
        :rows="rows"
        :trend="trendData"
        :months="months"
        :yoy-trend="yoyTrend"
        :yoy-months="yoyMonths"
        :rows-by-code="rowsByCode"
        @row-click="openDetail"
      />
    </section>

    <!-- 底部免责声明 -->
    <footer class="db-footer">
      <div class="footer-left">
        <svg class="footer-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="7"/><path d="M8 5v1M8 8v4"/></svg>
        数据来源：医院信息系统（HIS）| ICU质量管理系统（ICU-QMS）
      </div>
      <div class="footer-right">
        <svg class="footer-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="7"/><path d="M8 5v1M8 8v4"/></svg>
        本看板数据仅供医疗质量管理参考，不作为临床决策依据
      </div>
    </footer>

    <!-- 弹窗 -->
    <Modal v-if="guideVisible" title="指标口径说明" @close="guideVisible=false">
      <IndicatorGuideModal />
    </Modal>
    <Modal v-if="detailVisible" :title="detailTitle" @close="detailVisible=false">
      <DetailModal :data="detailData" :period="ps" :end-period="endPeriodParam" :unit="detailUnit" :unit-name="detailUnitName" />
    </Modal>
  </div>
</template>

<script setup>
import { ref, computed, inject, onMounted, onUnmounted, watch } from 'vue';
import { INDICATORS, getStatusConfig, statusText as getStatusLabel } from '../config/indicators.js';
import { INDICATOR_GROUPS, getGroupStats } from '../config/indicatorGroups.js';
import { fetchCommandCenter, fetchDetail } from '../api/index.js';
import { getMoM, getYoY, formatDelta, formatValue } from '../utils/compare.js';

// 组件
import DeltaBadge from '../components/DeltaBadge.vue';
import Sparkline from '../components/Sparkline.vue';
import RingProgress from '../components/RingProgress.vue';
import HBarRankChart from '../components/HBarRankChart.vue';
import GroupedBarChart from '../components/GroupedBarChart.vue';
import FunnelBundleChart from '../components/FunnelBundleChart.vue';
import RadarAssessChart from '../components/RadarAssessChart.vue';
import BarTargetChart from '../components/BarTargetChart.vue';
import CensusStackChart from '../components/CensusStackChart.vue';
import SmrChart from '../components/SmrChart.vue';
import ComparisonTable from '../components/ComparisonTable.vue';
import AiPanel from '../components/AiPanel.vue';
import Modal from '../components/Modal.vue';
import IndicatorGuideModal from '../components/IndicatorGuideModal.vue';
import DetailModal from '../components/DetailModal.vue';

// ---- 状态 ----
const year = ref(new Date().getFullYear());
const sMonth = ref(new Date().getMonth() + 1);
const eMonth = ref(new Date().getMonth() + 1);
const hostDeptCode = inject('hostDeptCode', ref('all'));
const dept = computed(() => hostDeptCode.value || 'all');
const years = [2024, 2025, 2026];
const compactMode = ref(false);

const rows = ref([]);
const rowsByCode = ref({});
const values = ref({});
const trendData = ref({});
const months = ref([]);
const risk = ref({ overall_status: 'unknown', counts: {} });
const abnormal = ref([]);
const ai = ref({ summary: '', hints: [], todos: [], tri_tube: {}, low_confidence: {} });
const loading = ref(false);
const error = ref('');
const updatedAt = ref('');
const statusConfig = ref(getStatusConfig());
const guideVisible = ref(false);
const censusData = ref(null);
const censusTrend = ref([]);

// 同比数据
const yoyTrend = ref(null);
const yoyMonths = ref(null);

// 弹窗
const detailVisible = ref(false);
const detailData = ref(null);
const detailTitle = ref('');
const detailUnit = ref('');
const detailUnitName = ref('');

const ps = computed(() => `${year.value}-${String(sMonth.value).padStart(2, '0')}`);
const pe = computed(() => `${year.value}-${String(eMonth.value).padStart(2, '0')}`);
const endPeriodParam = computed(() => sMonth.value === eMonth.value ? '' : pe.value);

// ---- 工具函数 ----
function displayCode(code) {
  return INDICATORS.find(i => i.code === code)?.displayCode || code;
}
function statusText(status) {
  return getStatusLabel(status, statusConfig.value);
}
function fmtValue(v) {
  return v == null || Number.isNaN(Number(v)) ? '/' : v;
}
function getIndicatorProp(code, prop) {
  return INDICATORS.find(i => i.code === code)?.[prop] || '';
}

// ---- 分组 ----
const structureCodes = computed(() => {
  const group = INDICATOR_GROUPS.find(g => g.id === 'structure');
  return (group?.codes || []).filter(c => rowsByCode.value[c]);
});

const processCodes = computed(() => {
  const group = INDICATOR_GROUPS.find(g => g.id === 'process');
  return (group?.codes || []).filter(c => rowsByCode.value[c]);
});

const outcomeCodes = computed(() => {
  const group = INDICATOR_GROUPS.find(g => g.id === 'outcome');
  return (group?.codes || []).filter(c => rowsByCode.value[c]);
});

// 分区统计
const zoneStats = computed(() => {
  const stats = {};
  for (const g of INDICATOR_GROUPS) {
    if (['structure', 'process', 'outcome'].includes(g.id)) {
      stats[g.id] = getGroupStats(g, rowsByCode.value);
    }
  }
  return stats;
});

// ---- KPI 卡片（6 张） ----
const kpiCardCodes = ['ICU-01', 'ICU-04', 'ICU-06', 'ICU-11', 'ICU-16', 'ICU-17'];
const kpiCards = computed(() => {
  return kpiCardCodes.map(code => {
    const row = rowsByCode.value[code];
    if (!row || row.value == null) return null;

    const mom = getMoM(code, trendData.value, months.value, row.denominator);
    const yoy = getYoY(code, trendData.value, months.value, yoyTrend.value, yoyMonths.value, row.denominator);
    const momFmt = formatDelta(mom, 'mom');
    const yoyFmt = formatDelta(yoy, 'yoy');

    return {
      code,
      name: row.name,
      value: row.value,
      valueText: formatValue(row.value, code),
      unit: row.unit || '',
      status: row.status || 'unknown',
      momText: momFmt.text,
      momTooltip: momFmt.tooltip,
      momClass: momFmt.cssClass,
      momArrow: momFmt.arrow,
      momSmall: momFmt.smallSample,
      yoyText: yoyFmt.text,
      yoyTooltip: yoyFmt.tooltip,
      yoyClass: yoyFmt.cssClass,
      yoyArrow: yoyFmt.arrow,
      yoySmall: yoyFmt.smallSample,
    };
  }).filter(Boolean);
});

// ---- 异常列表 ----
const abnormalList = computed(() => (abnormal.value || []).filter(i => {
  if (i.status === 'unknown') return false;
  const ind = INDICATORS.find(x => x.code === i.code);
  return !ind?.excludeFromAlert;
}).slice(0, 8));

// ---- 过程区 hbar ----
const processHbarItems = computed(() => {
  return processCodes.value.map(code => {
    const row = rowsByCode.value[code];
    if (!row) return null;
    const ind = INDICATORS.find(i => i.code === code);
    const target = ind?.thresholds?.good?.[0] || 80;
    return { name: row.name, value: row.value, target, status: row.status };
  }).filter(Boolean);
});

// ---- 结果区 hbar ----
const outcomeHbarItems = computed(() => {
  return outcomeCodes.value.filter(c => c !== 'ICU-11').map(code => {
    const row = rowsByCode.value[code];
    if (!row) return null;
    const ind = INDICATORS.find(i => i.code === code);
    const target = ind?.thresholds?.good?.[1] || 5;
    return { name: row.name, value: row.value, target, status: row.status };
  }).filter(Boolean);
});

// ---- SMR ----
const smrCurrent = computed(() => values.value['ICU-11'] ?? 1);
const smrHistory = computed(() => trendData.value['ICU-11'] ?? []);

// ---- 感染防控组 ----
const infectionCategories = computed(() => {
  return ['VAP', 'CRBSI', 'CAUTI'].filter((_, i) => {
    const codes = ['ICU-16', 'ICU-17', 'CAUTI'];
    return rowsByCode.value[codes[i]]?.value != null;
  });
});
const infectionSeries = computed(() => {
  const codes = ['ICU-16', 'ICU-17', 'CAUTI'];
  return [{
    name: '本期',
    data: codes.map(c => rowsByCode.value[c]?.value ?? 0),
    color: '#1e5eb8',
  }];
});

// ---- Sepsis 漏斗 ----
const bundleFunnelData = computed(() => {
  const codes = ['ICU-05-1h', 'ICU-05-3h', 'ICU-05-6h'];
  return codes.map(code => {
    const row = rowsByCode.value[code];
    return {
      code,
      name: row?.name?.replace('感染性休克', '').replace('完成率', '') || code,
      value: row?.value || 0,
    };
  });
});

// ---- 镇痛镇静雷达 ----
const sedationRadarData = computed(() => {
  const codes = ['ICU-09', 'ICU-10', 'ICU-18'];
  return codes.map(code => {
    const row = rowsByCode.value[code];
    const ind = INDICATORS.find(i => i.code === code);
    return {
      code,
      name: row?.name || code,
      value: row?.value || 0,
      target: ind?.thresholds?.good?.[0] || 90,
    };
  });
});

// ---- 人力配置 ----
const ratioItems = computed(() => [
  { name: '医生床位比', value: values.value['ICU-02'] ?? 0, target: 0.8 },
  { name: '护士床位比', value: values.value['ICU-03'] ?? 0, target: 2.5 },
]);

// ---- 气道安全 ----
const airwayCategories = computed(() => {
  return ['非计划拔管', '48h再插管'].filter((_, i) => {
    const codes = ['ICU-12', 'ICU-13'];
    return rowsByCode.value[codes[i]]?.value != null;
  });
});
const airwaySeries = computed(() => {
  const codes = ['ICU-12', 'ICU-13'];
  return [{
    name: '本期',
    data: codes.map(c => rowsByCode.value[c]?.value ?? 0),
    color: '#c62828',
  }];
});

// ---- 总体 ----
const overallText = computed(() => {
  if (risk.value.overall_status === 'danger') return '异常';
  if (risk.value.overall_status === 'warn') return '预警';
  if (risk.value.overall_status === 'good') return '平稳';
  return '待刷新';
});
const periodLabel = computed(() => {
  if (sMonth.value === eMonth.value) return `${year.value}年${sMonth.value}月`;
  return `${year.value}年${sMonth.value}月 至 ${eMonth.value}月`;
});

// ---- 交互 ----
async function openDetail(row) {
  if (!row || !row.code) return;
  detailTitle.value = `${displayCode(row.code)} ${row.name} — 患者明细`;
  detailUnit.value = row.unit || '';
  detailUnitName.value = row.name;
  detailVisible.value = true;

  const base = { name: row.name, code: row.code, part: 'numerator', loading: true, patients: [], source_desc: '加载中...', count: 0 };
  detailData.value = base;
  try {
    detailData.value = await fetchDetail(row.code, ps.value, 'numerator', dept.value, endPeriodParam.value, { limit: 200, offset: 0 });
  } catch (e) {
    detailData.value = { ...base, loading: false, error: e.message || '明细加载失败', source_desc: '明细加载失败' };
  }
}

function handleChartClick(params) {
  if (params?.name) {
    const row = rows.value.find(r => r.name === params.name);
    if (row) openDetail(row);
  }
}

// ---- 数据加载 ----
let yoyCache = {};

async function loadData(nocache = false) {
  if (eMonth.value < sMonth.value) eMonth.value = sMonth.value;
  loading.value = true;
  error.value = '';
  try {
    const res = await fetchCommandCenter(ps.value, endPeriodParam.value, dept.value, nocache);
    rows.value = res.rows || [];
    rowsByCode.value = Object.fromEntries(rows.value.map(r => [r.code, r]));
    values.value = res.values || {};
    trendData.value = res.trend || {};
    months.value = res.months || [];
    risk.value = res.risk || { overall_status: 'unknown', counts: {} };
    abnormal.value = res.abnormal || [];
    ai.value = res.ai || { summary: '', hints: [], todos: [] };
    updatedAt.value = res.updated_at ? res.updated_at.replace('T', ' ') : '';
    censusData.value = res.census || null;
    censusTrend.value = res.census_trend || [];

    // 尝试获取去年同期数据
    loadYoYData();
  } catch (e) {
    error.value = e.message || '大屏数据读取失败';
    rows.value = [];
    rowsByCode.value = {};
    values.value = {};
    trendData.value = {};
    abnormal.value = [];
  } finally {
    loading.value = false;
  }
}

async function loadYoYData() {
  const yoyYear = year.value - 1;
  const yoyPeriod = `${yoyYear}-${String(sMonth.value).padStart(2, '0')}`;
  const yoyEnd = sMonth.value === eMonth.value ? '' : `${yoyYear}-${String(eMonth.value).padStart(2, '0')}`;
  const cacheKey = `${yoyPeriod}-${yoyEnd}-${dept.value}`;

  if (yoyCache[cacheKey]) {
    yoyTrend.value = yoyCache[cacheKey].trend;
    yoyMonths.value = yoyCache[cacheKey].months;
    return;
  }

  try {
    const res = await fetchCommandCenter(yoyPeriod, yoyEnd, dept.value);
    if (res.trend && res.months) {
      yoyTrend.value = res.trend;
      yoyMonths.value = res.months;
      yoyCache[cacheKey] = { trend: res.trend, months: res.months };
    } else {
      yoyTrend.value = null;
      yoyMonths.value = null;
    }
  } catch {
    // 后端不支持跨年查询，显示「—」
    yoyTrend.value = null;
    yoyMonths.value = null;
  }
}

// ---- URL 同步 ----
function syncFromURL() {
  const p = new URLSearchParams(window.location.search);
  const y = p.get('year'); if (y) year.value = +y;
  const sm = p.get('sMonth'); if (sm) sMonth.value = +sm;
  const em = p.get('eMonth'); if (em) eMonth.value = +em;
}
function syncToURL() {
  const u = new URL(window.location);
  u.searchParams.set('year', year.value);
  u.searchParams.set('sMonth', sMonth.value);
  u.searchParams.set('eMonth', eMonth.value);
  window.history.replaceState({}, '', u);
}
watch([year, sMonth, eMonth], syncToURL);
watch(hostDeptCode, () => { loadData(true); });

onMounted(() => {
  window.addEventListener('status-config-updated', () => {
    statusConfig.value = getStatusConfig();
  });
  syncFromURL();
  loadData();
});
</script>

<style scoped>
.dashboard {
  padding: 18px 24px 0;
  min-height: 100vh;
  background: var(--bg-app);
  color: var(--text-body);
}
.dashboard.compact {
  padding: 10px 16px 0;
}
.dashboard.compact .kpi-stat-card { margin-bottom: 8px; }
.dashboard.compact .zone-section { margin-bottom: 12px; }
.dashboard.compact .panel { padding: 10px 12px; }

/* ---- Header ---- */
.db-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 16px;
  gap: 16px;
  flex-wrap: wrap;
}
.db-header-left { display: flex; flex-direction: column; gap: 2px; }
.db-title {
  font-size: var(--fs-h1); font-weight: 600; color: var(--text-title);
  line-height: 1.3; margin: 0;
}
.db-subtitle { font-size: var(--fs-caption); color: var(--text-sub); }
.db-header-right { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }

/* Anchor nav */
.anchor-nav { display: flex; gap: 2px; }
.anchor-link {
  padding: 4px 10px; border-radius: 6px; font-size: 12px; color: var(--text-sub);
  text-decoration: none; transition: all .15s;
}
.anchor-link:hover { background: var(--brand-weak); color: var(--brand); }

/* Period selector */
.period-selector { display: flex; align-items: center; gap: 6px; }
.period-label { font-size: var(--fs-caption); color: var(--text-sub); white-space: nowrap; }
.period-to { font-size: var(--fs-label); color: var(--text-sub); padding: 0 2px; }
.period-selector select {
  background: var(--bg-surface); color: var(--text-body);
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 6px 10px; font-size: var(--fs-label); height: 32px;
  transition: border-color .2s;
}
.period-selector select:focus { border-color: var(--brand); outline: none; box-shadow: 0 0 0 2px var(--brand-weak); }

/* Density button */
.density-btn {
  display: flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-surface); color: var(--text-sub); cursor: pointer; transition: all .15s;
}
.density-btn:hover { border-color: var(--brand); color: var(--brand); }
.density-btn svg { width: 16px; height: 16px; }

/* Status pill */
.status-pill {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 12px; border-radius: 20px;
  font-size: var(--fs-caption); font-weight: 600;
  background: var(--brand-weak); color: var(--brand);
  border: 1px solid rgba(30,94,184,0.2);
}
.status-pill.danger { background: var(--danger-weak); color: var(--danger); border-color: rgba(198,40,40,0.2); }
.status-pill.warn { background: var(--warn-weak); color: var(--warn); border-color: rgba(178,106,0,0.2); }
.status-pill.good { background: var(--good-weak); color: var(--good); border-color: rgba(14,122,82,0.2); }
.pill-icon { width: 14px; height: 14px; flex-shrink: 0; }
.meta-update { color: var(--text-faint); font-size: var(--fs-caption); white-space: nowrap; }

/* State messages */
.state {
  margin-bottom: 12px; padding: 10px 14px; border-radius: var(--radius-sm);
  background: var(--brand-weak); color: var(--text-sub); font-size: var(--fs-body);
  border: 1px solid rgba(30,94,184,0.15); display: flex; align-items: center; gap: 8px;
}
.state.error { background: var(--danger-weak); color: var(--danger); border-color: rgba(198,40,40,0.15); }
.spin-icon { width: 16px; height: 16px; animation: spin 1s linear infinite; flex-shrink: 0; }
@keyframes spin { to { transform: rotate(360deg); } }

/* KPI Stat Cards */
.kpi-stats {
  display: grid; grid-template-columns: repeat(6, 1fr);
  gap: 12px; margin-bottom: 14px;
}
.kpi-stat-card {
  display: flex; background: var(--bg-surface);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  overflow: hidden; transition: border-color .2s, box-shadow .2s;
  box-shadow: var(--shadow-card); cursor: pointer;
}
.kpi-stat-card:hover { border-color: var(--border-strong); box-shadow: 0 2px 8px rgba(16,24,40,.08); }
.kpi-card-left { width: 4px; flex-shrink: 0; background: var(--text-faint); }
.kpi-stat-card.good .kpi-card-left { background: var(--good); }
.kpi-stat-card.warn .kpi-card-left { background: var(--warn); }
.kpi-stat-card.danger .kpi-card-left { background: var(--danger); }
.kpi-card-body { padding: 12px 14px; flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.kpi-card-top { display: flex; justify-content: space-between; align-items: center; }
.kpi-card-label { font-size: var(--fs-caption); color: var(--text-sub); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kpi-card-code { font-size: 11px; color: var(--brand); font-weight: 700; }
.kpi-card-main { display: flex; align-items: baseline; gap: 3px; }
.kpi-card-big { font-size: var(--fs-metric); font-weight: 700; color: var(--text-title); line-height: 1.2; }
.kpi-card-unit { font-size: var(--fs-body); color: var(--text-sub); }
.kpi-card-deltas { display: flex; gap: 4px; flex-wrap: wrap; }

/* Abnormal + AI strip */
.abnormal-ai-strip {
  display: grid; grid-template-columns: 1.2fr 1fr; gap: 12px; margin-bottom: 14px;
}

/* Panel base */
.panel {
  background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 14px 16px; box-shadow: var(--shadow-card); min-width: 0;
}
.panel-title {
  font-size: var(--fs-h2); color: var(--text-title); font-weight: 600;
  margin-bottom: 12px; padding-left: 10px; border-left: 3px solid var(--brand);
  display: flex; align-items: center; gap: 8px;
}
.panel-icon { width: 16px; height: 16px; color: var(--text-sub); flex-shrink: 0; }

/* Abnormal list */
.abnormal-list { display: flex; flex-direction: column; gap: 8px; max-height: 360px; overflow: auto; padding-right: 2px; }
.abnormal-item {
  border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 12px;
  background: var(--bg-subtle); transition: border-color .15s; cursor: pointer;
}
.abnormal-item:hover { border-color: var(--border-strong); }
.abnormal-item.danger { background: var(--danger-weak); border-left: 3px solid var(--danger); }
.abnormal-item.warn { background: var(--warn-weak); border-left: 3px solid var(--warn); }
.ab-main { display: flex; align-items: center; gap: 8px; min-width: 0; }
.ab-code { color: var(--brand); font-weight: 700; font-size: var(--fs-caption); }
.ab-main strong { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--fs-label); color: var(--text-title); }
.ab-status { font-size: var(--fs-caption); color: var(--text-sub); }
.ab-meta { margin-top: 6px; color: var(--text-faint); font-size: var(--fs-caption); line-height: 1.5; }
.abnormal-count {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 20px; height: 20px; border-radius: 10px; font-size: 11px; font-weight: 700;
  background: var(--danger); color: #fff; padding: 0 6px;
}
.empty {
  color: var(--text-faint); font-size: var(--fs-body); padding: 24px; text-align: center;
  background: var(--bg-subtle); border: 1px dashed var(--border-strong); border-radius: var(--radius-sm);
  display: flex; flex-direction: column; align-items: center; gap: 8px;
}
.empty-icon { width: 24px; height: 24px; color: var(--text-faint); }

/* Zone sections */
.zone-section {
  margin-bottom: 18px;
}
.zone-title-bar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 12px; padding: 10px 14px;
  background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
}
.zone-title {
  font-size: var(--fs-h1); font-weight: 600; color: var(--text-title); margin: 0;
  display: flex; align-items: center; gap: 8px;
}
.zone-icon { width: 18px; height: 18px; color: var(--brand); flex-shrink: 0; }
.zone-stats { display: flex; gap: 8px; }
.zone-stat {
  font-size: 12px; font-weight: 600; padding: 3px 8px; border-radius: 4px;
}
.zone-stat.good { color: var(--good); background: var(--good-weak); }
.zone-stat.warn { color: var(--warn); background: var(--warn-weak); }
.zone-stat.danger { color: var(--danger); background: var(--danger-weak); }

/* Zone grids */
.zone-grid {
  display: grid; gap: 12px;
}
.ring-grid {
  grid-template-columns: repeat(4, 1fr);
}
.ring-grid-wrap {
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  margin-bottom: 12px;
}
.zone-cell {
  background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 12px; box-shadow: var(--shadow-card); cursor: pointer;
  transition: border-color .15s, box-shadow .15s;
}
.zone-cell:hover { border-color: var(--border-strong); box-shadow: 0 2px 8px rgba(16,24,40,.08); }
.zone-chart {
  background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 14px 16px; box-shadow: var(--shadow-card); margin-top: 12px;
}
.smr-row {
  background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 14px 16px; box-shadow: var(--shadow-card); margin-top: 12px;
}

/* Combo grid */
.combo-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
}
.combo-panel { min-height: 0; }

/* Footer */
.db-footer {
  display: flex; justify-content: space-between; align-items: center;
  margin-top: 16px; padding: 12px 16px; background: var(--bg-subtle);
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  font-size: var(--fs-caption); color: var(--text-faint);
}
.footer-icon { width: 14px; height: 14px; margin-right: 4px; vertical-align: -2px; }

/* Responsive */
@media (max-width: 1400px) {
  .kpi-stats { grid-template-columns: repeat(3, 1fr); }
  .ring-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 1200px) {
  .abnormal-ai-strip { grid-template-columns: 1fr; }
  .combo-grid { grid-template-columns: 1fr; }
}
@media (max-width: 960px) {
  .kpi-stats { grid-template-columns: repeat(2, 1fr); }
  .db-header { flex-direction: column; align-items: flex-start; }
  .db-header-right { width: 100%; }
  .ring-grid { grid-template-columns: 1fr; }
}
</style>
