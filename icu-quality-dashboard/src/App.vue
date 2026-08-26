<template>
  <div class="app-shell">
    <!-- 顶部深蓝导航栏 -->
    <header class="topnav">
      <div class="topnav-brand">
        <span class="brand-cross">✚</span>
        <span class="brand-text">ICU 质控中心</span>
      </div>
      <nav class="topnav-links">
        <button
          v-for="item in navItems"
          :key="item.key"
          :class="['topnav-item', { active: currentView === item.key }]"
          @click="currentView = item.key"
        >{{ item.label }}</button>
      </nav>
      <div class="topnav-actions">
        <button class="nav-btn dashboard-btn" @click="openDashboard" title="实时大屏">📊 实时大屏</button>
        <button class="nav-btn config-btn" @click="openConfig" title="状态配置">⚙ 配置</button>
      </div>
    </header>

    <!-- 主内容区 -->
    <main class="app-main">
      <KeepAlive>
        <component :is="views[currentView]" />
      </KeepAlive>
    </main>

    <!-- 全局指标说明弹窗 -->
    <Modal v-if="guideVisible" title="指标口径说明" @close="guideVisible = false">
      <IndicatorGuideModal />
    </Modal>
  </div>
</template>

<script setup>
import { ref, provide, onMounted, onUnmounted } from 'vue';
import Dashboard from './views/Dashboard.vue';
import StatusConfig from './views/StatusConfig.vue';
import IndicatorTable from './IndicatorTable.vue';
import Modal from './components/Modal.vue';
import IndicatorGuideModal from './components/IndicatorGuideModal.vue';

const currentView = ref('table');
const guideVisible = ref(false);
const hostDeptCode = ref('');
const hostPatient = ref(null);

provide('hostDeptCode', hostDeptCode);
provide('hostPatient', hostPatient);

const navItems = [
  { key: 'table', label: '指标管理' },
];

const views = {
  dashboard: Dashboard,
  statusConfig: StatusConfig,
  table: IndicatorTable,
};

function openDashboard() { currentView.value = 'dashboard'; }
function openConfig() { currentView.value = 'statusConfig'; }
function navigateView(e) { currentView.value = e.detail; }

// ===== postMessage 通信 =====
const PRINT_ORIGIN = '*'; // 联调阶段用 *，正式部署替换为宿主来源
const printOrigin = ref(PRINT_ORIGIN);

function onSmartCareReady(e) {
  if (e.data?.type !== 'SmartCareReady') return;
  const patient = hostPatient.value || {};
  window.parent.postMessage({
    type: 'SmartCare',
    account: null,
    patient,
    token: null,
  }, printOrigin.value);
}

function onSmartCare(e) {
  if (e.data?.type !== 'SmartCare') return;
  const patient = e.data.patient || {};
  hostPatient.value = patient;
  hostDeptCode.value = patient.deptCode || patient.deptCode2 || '';
}

function onHostMessage(e) {
  onSmartCareReady(e);
  onSmartCare(e);
}

onMounted(() => {
  window.addEventListener('message', onHostMessage);
  window.addEventListener('navigate-view', navigateView);
  // 通知宿主：打印程序已就绪
  window.parent.postMessage({ type: 'SmartCareReady' }, printOrigin.value);
});

onUnmounted(() => {
  window.removeEventListener('message', onHostMessage);
  window.removeEventListener('navigate-view', navigateView);
});
</script>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

/* ---- Top Navigation Bar ---- */
.topnav {
  display: flex;
  align-items: center;
  background: var(--nav-bg);
  padding: 0 20px;
  height: 48px;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(0,0,0,0.15);
  z-index: 100;
}
.topnav-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-right: 32px;
  flex-shrink: 0;
}
.brand-cross { font-size: 18px; color: #fff; }
.brand-text { font-size: 14px; font-weight: 700; color: #fff; white-space: nowrap; }

.topnav-links { display: flex; align-items: center; gap: 0; flex: 1; }
.topnav-item {
  background: none; border: none; color: var(--nav-text);
  font-size: 14px; padding: 14px 20px; cursor: pointer;
  transition: all 0.2s; white-space: nowrap; position: relative;
}
.topnav-item:hover { color: #fff; background: var(--nav-hover); }
.topnav-item.active { color: var(--nav-active); font-weight: 600; }
.topnav-item.active::after {
  content: ''; position: absolute; bottom: 0; left: 50%;
  transform: translateX(-50%); width: 32px; height: 3px;
  background: #5b9bd5; border-radius: 2px 2px 0 0;
}

.topnav-actions { display: flex; align-items: center; gap: 8px; margin-left: auto; flex-shrink: 0; }
.nav-btn {
  padding: 6px 16px; border-radius: 6px; border: none;
  font-size: 13px; font-weight: 500; cursor: pointer;
  transition: all 0.2s; white-space: nowrap;
}
.dashboard-btn { background: #2B5EA7; color: #fff; }
.dashboard-btn:hover { background: #3a72bf; }
.config-btn { background: rgba(255,255,255,0.12); color: #fff; border: 1px solid rgba(255,255,255,0.2); }
.config-btn:hover { background: rgba(255,255,255,0.2); }

/* ---- Main Content ---- */
.app-main { flex: 1; padding: 16px 24px; overflow: auto; background: var(--bg-body); }
</style>
