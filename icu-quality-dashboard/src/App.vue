<template>
  <div class="app-shell">
    <!-- 顶部导航栏 -->
    <header class="topnav">
      <div class="topnav-brand">
        <svg class="brand-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M8 1v14M1 8h14M4 4l8 8M12 4l-8 8"/>
        </svg>
        <span class="brand-text">ICU 医疗质量控制中心</span>
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
        <button class="ghost-btn" @click="refreshCurrent" title="刷新数据">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M1 8a7 7 0 0 1 13.1-3.5M15 1v4h-4M15 8a7 7 0 0 1-13.1 3.5M1 15v-4h4"/></svg>
        </button>
        <button class="ghost-btn" @click="guideVisible=true" title="指标说明">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="7"/><path d="M6 6a2 2 0 1 1 2 2v2M8 12h.01"/></svg>
        </button>
        <button class="ghost-btn" @click="toggleFullscreen" title="全屏">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M1 5V1h4M15 5V1h-4M1 11v4h4M15 11v4h-4"/></svg>
        </button>
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
import Cockpit from './views/Cockpit.vue';
import StatusConfig from './views/StatusConfig.vue';
import IndicatorTable from './IndicatorTable.vue';
import Modal from './components/Modal.vue';
import IndicatorGuideModal from './components/IndicatorGuideModal.vue';
import { fetchDepartments } from './api/index.js';

const currentView = ref('table');
const guideVisible = ref(false);
const hostDeptCode = ref('');
const hostDeptName = ref('');
const hostPatient = ref(null);
/** code → { name, shortName } 缓存 */
const deptNameMap = ref({});

provide('hostDeptCode', hostDeptCode);
provide('hostDeptName', hostDeptName);
provide('hostPatient', hostPatient);

async function loadDeptMap() {
  try {
    const list = await fetchDepartments();
    const map = {};
    for (const d of list || []) {
      const code = String(d.code ?? d.deptCode ?? '');
      if (!code) continue;
      map[code] = {
        name: d.name || d.shortName || code,
        shortName: d.shortName || d.name || code,
      };
    }
    deptNameMap.value = map;
    resolveDeptName();
  } catch { /* 科室接口失败时仅显示编码 */ }
}

function resolveDeptName() {
  const code = hostDeptCode.value;
  if (!code || code === 'all') {
    hostDeptName.value = '';
    return;
  }
  const hit = deptNameMap.value[code];
  hostDeptName.value = hit?.shortName || hit?.name || '';
}

const navItems = [
  { key: 'dashboard', label: '大屏总览' },
  { key: 'cockpit',   label: '驾驶舱' },
  { key: 'table',     label: '指标管理' },
  { key: 'statusConfig', label: '状态配置' },
];

const views = {
  dashboard: Dashboard,
  cockpit: Cockpit,
  statusConfig: StatusConfig,
  table: IndicatorTable,
};

function navigateView(e) { currentView.value = e.detail; }

function refreshCurrent() {
  window.dispatchEvent(new CustomEvent('refresh-data'));
}

function toggleFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen?.();
  } else {
    document.exitFullscreen?.();
  }
}

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

function applyDeptCode(code, nameFromHost = '') {
  if (code) {
    hostDeptCode.value = String(code);
    try {
      const u = new URL(window.location.href);
      if (u.searchParams.get('deptCode') !== hostDeptCode.value) {
        u.searchParams.set('deptCode', hostDeptCode.value);
        window.history.replaceState({}, '', u);
      }
    } catch { /* ignore */ }
  }
  // 宿主优先带科室名；否则查 department 表映射
  if (nameFromHost) {
    hostDeptName.value = String(nameFromHost);
  } else {
    resolveDeptName();
  }
}

function onSmartCare(e) {
  if (e.data?.type !== 'SmartCare') return;
  const patient = e.data.patient || {};
  hostPatient.value = patient;
  applyDeptCode(
    patient.deptCode || patient.deptCode2 || '',
    patient.deptName || patient.deptName2 || patient.dept || '',
  );
}

function onHostMessage(e) {
  onSmartCareReady(e);
  onSmartCare(e);
}

onMounted(() => {
  window.addEventListener('message', onHostMessage);
  window.addEventListener('navigate-view', navigateView);
  loadDeptMap();
  // 本地/无宿主时：从 URL 读 deptCode（如 ?deptCode=3439），与地址栏一致
  if (!hostDeptCode.value) {
    try {
      const fromUrl = new URLSearchParams(window.location.search).get('deptCode');
      if (fromUrl) applyDeptCode(fromUrl);
    } catch { /* ignore */ }
  }
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
  background: var(--bg-surface);
  padding: 0 20px;
  height: 56px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
  z-index: 100;
}
.topnav-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-right: 32px;
  flex-shrink: 0;
}
.brand-icon { width: 16px; height: 16px; color: var(--brand); flex-shrink: 0; }
.brand-text { font-size: var(--fs-h2); font-weight: 600; color: var(--text-title); white-space: nowrap; }

.topnav-links { display: flex; align-items: center; gap: 0; flex: 1; }
.topnav-item {
  background: none; border: none; color: var(--text-sub);
  font-size: var(--fs-body); padding: 16px 20px; cursor: pointer;
  transition: all 0.2s; white-space: nowrap; position: relative;
}
.topnav-item:hover { color: var(--text-title); background: var(--bg-hover); }
.topnav-item.active { color: var(--brand); font-weight: 600; }
.topnav-item.active::after {
  content: ''; position: absolute; bottom: 0; left: 50%;
  transform: translateX(-50%); width: 32px; height: 2px;
  background: var(--brand); border-radius: 2px 2px 0 0;
}

.topnav-actions { display: flex; align-items: center; gap: 4px; margin-left: auto; flex-shrink: 0; }
.ghost-btn {
  width: 32px; height: 32px; border-radius: 8px; border: none;
  background: transparent; color: var(--text-sub); cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
  transition: all 0.2s;
}
.ghost-btn svg { width: 16px; height: 16px; }
.ghost-btn:hover { background: var(--bg-hover); color: var(--text-title); }

/* ---- Main Content ---- */
.app-main { flex: 1; overflow: auto; background: var(--bg-app); }
</style>
