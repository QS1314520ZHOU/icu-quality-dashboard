<template>
  <div class="app-shell" :class="{ collapsed: sidebarCollapsed }">
    <!-- 左侧边栏 -->
    <aside class="sidebar">
      <div class="sidebar-brand">
        <span class="brand-icon">🏥</span>
        <transition name="fade">
          <span v-if="!sidebarCollapsed" class="brand-text">ICU 医疗质量控制中心</span>
        </transition>
      </div>

      <nav class="sidebar-nav">
        <button
          v-for="item in navItems"
          :key="item.key"
          :class="['nav-item', { active: currentView === item.key }]"
          @click="currentView = item.key"
          :title="item.label"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          <transition name="fade">
            <span v-if="!sidebarCollapsed" class="nav-label">{{ item.label }}</span>
          </transition>
        </button>
      </nav>

      <div class="sidebar-footer">
        <div class="user-info">
          <div class="avatar">👤</div>
          <transition name="fade">
            <div v-if="!sidebarCollapsed" class="user-detail">
              <strong>admin</strong>
              <small>系统管理员</small>
            </div>
          </transition>
        </div>
        <button class="collapse-btn" @click="toggleSidebar" :title="sidebarCollapsed ? '展开菜单' : '收起菜单'">
          <span>{{ sidebarCollapsed ? '→' : '← 收起菜单' }}</span>
        </button>
      </div>
    </aside>

    <!-- 主内容 -->
    <div class="main-area">
      <header class="topbar">
        <div class="topbar-title">{{ currentTitle }}</div>
        <div class="topbar-actions">
          <button class="action-btn" @click="guideVisible = true" v-if="currentView === 'table'">指标说明</button>
        </div>
      </header>
      <main class="app-main">
        <KeepAlive>
          <component :is="views[currentView]" />
        </KeepAlive>
      </main>
    </div>

    <!-- 全局指标说明弹窗 -->
    <Modal v-if="guideVisible" title="指标口径说明" @close="guideVisible = false">
      <IndicatorGuideModal />
    </Modal>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue';
import Dashboard from './views/Dashboard.vue';
import StatusConfig from './views/StatusConfig.vue';
import IndicatorTable from './IndicatorTable.vue';
import Modal from './components/Modal.vue';
import IndicatorGuideModal from './components/IndicatorGuideModal.vue';

const SIDEBAR_KEY = 'icu-sidebar-collapsed';
const sidebarCollapsed = ref(localStorage.getItem(SIDEBAR_KEY) === 'true');
const currentView = ref('table');
const guideVisible = ref(false);

const navItems = [
  { key: 'table', icon: '📋', label: '指标管理' },
  { key: 'dashboard', icon: '📊', label: '实时大屏' },
  { key: 'statusConfig', icon: '⚙', label: '状态配置' },
];

const views = {
  dashboard: Dashboard,
  statusConfig: StatusConfig,
  table: IndicatorTable,
};

const currentTitle = computed(() => {
  const item = navItems.find(n => n.key === currentView.value);
  return item ? item.label : '';
});

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value;
  localStorage.setItem(SIDEBAR_KEY, String(sidebarCollapsed.value));
}
</script>

<style scoped>
.app-shell { display:flex; min-height:100vh; }

/* ---- Sidebar ---- */
.sidebar {
  width: var(--sidebar-width);
  background: var(--sidebar-bg);
  display: flex;
  flex-direction: column;
  transition: width .25s ease;
  flex-shrink: 0;
  overflow: hidden;
}
.app-shell.collapsed .sidebar { width: var(--sidebar-collapsed); }

.sidebar-brand {
  display:flex; align-items:center; gap:10px;
  padding:18px 16px; border-bottom:1px solid rgba(255,255,255,0.06);
}
.brand-icon { font-size:22px; flex-shrink:0; }
.brand-text { font-size:14px; font-weight:700; color:#fff; white-space:nowrap; }

.sidebar-nav { flex:1; padding:12px 8px; overflow-y:auto; }
.nav-item {
  width:100%; display:flex; align-items:center; gap:10px;
  padding:10px 12px; border:none; border-radius:8px;
  background:transparent; color:var(--sidebar-text);
  font-size:13px; cursor:pointer; transition:all .2s;
  white-space:nowrap; text-align:left;
}
.nav-item:hover { background:var(--sidebar-hover); color:#fff; }
.nav-item.active { background:var(--sidebar-active); color:#fff; font-weight:600; }
.nav-icon { font-size:16px; flex-shrink:0; text-align:center; width:20px; }
.nav-label { font-size:13px; }

.sidebar-footer {
  padding:12px; border-top:1px solid rgba(255,255,255,0.06);
}
.user-info { display:flex; align-items:center; gap:10px; margin-bottom:10px; }
.avatar { width:32px; height:32px; border-radius:50%; background:rgba(255,255,255,0.1);
  display:flex; align-items:center; justify-content:center; font-size:14px; flex-shrink:0; }
.user-detail strong { display:block; color:#fff; font-size:12px; }
.user-detail small { color:var(--sidebar-text); font-size:11px; }
.collapse-btn {
  width:100%; padding:8px; border:1px solid rgba(255,255,255,0.1);
  border-radius:6px; background:transparent; color:var(--sidebar-text);
  font-size:12px; cursor:pointer; transition:all .2s;
}
.collapse-btn:hover { background:rgba(255,255,255,0.05); color:#fff; }

/* ---- Main area ---- */
.main-area { flex:1; display:flex; flex-direction:column; min-width:0; }
.topbar {
  display:flex; justify-content:space-between; align-items:center;
  padding:14px 24px; background:var(--bg-card);
  border-bottom:1px solid var(--border);
}
.topbar-title { font-size:16px; font-weight:600; color:var(--text-main); }
.topbar-actions { display:flex; gap:10px; }
.action-btn {
  padding:7px 16px; border-radius:7px; font-size:13px; font-weight:500;
  background:var(--brand); color:#fff; border:none; cursor:pointer;
}
.app-main { flex:1; padding:16px 24px; overflow:auto; }

/* ---- Transitions ---- */
.fade-enter-active, .fade-leave-active { transition: opacity .2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>