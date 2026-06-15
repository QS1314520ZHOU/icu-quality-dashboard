<template>
  <div class="app-container">
    <!-- 全局精美导航栏 -->
    <nav class="app-nav">
      <div class="nav-brand">
        <span class="nav-logo">🏥</span> ICU 医疗质量控制中心
      </div>
      <div class="nav-links">
        <button 
          :class="['nav-btn', { active: currentView === 'table' }]" 
          @click="currentView = 'table'"
        >
          📋 指标明细表
        </button>
        <button 
          :class="['nav-btn', { active: currentView === 'dashboard' }]" 
          @click="currentView = 'dashboard'"
        >
          📊 实时大屏看板
        </button>
        <button
          :class="['nav-btn', { active: currentView === 'statusConfig' }]"
          @click="currentView = 'statusConfig'"
        >
          ⚙ 状态配置
        </button>
      </div>
    </nav>
    
    <!-- 主视图区 -->
    <main class="app-main">
      <KeepAlive>
        <component :is="views[currentView]" />
      </KeepAlive>
    </main>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import Dashboard from './views/Dashboard.vue';
import StatusConfig from './views/StatusConfig.vue';
import IndicatorTable from './IndicatorTable.vue';

const currentView = ref('table'); // 默认显示指标明细表

const views = {
  dashboard: Dashboard,
  statusConfig: StatusConfig,
  table: IndicatorTable
};
</script>

<style scoped>
.app-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
.app-nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #ffffff;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  padding: 12px 28px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
.nav-brand {
  font-size: 18px;
  font-weight: bold;
  color: #1e293b;
  display: flex;
  align-items: center;
  gap: 8px;
}
.nav-logo {
  font-size: 20px;
}
.nav-links {
  display: flex;
  gap: 12px;
}
.nav-btn {
  background: transparent;
  border: 1px solid rgba(0, 82, 217, 0.15);
  color: #64748b;
  padding: 8px 18px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.nav-btn:hover {
  background: rgba(0, 82, 217, 0.04);
  color: #0052d9;
  border-color: rgba(0, 82, 217, 0.4);
}
.nav-btn.active {
  background: #0052d9;
  color: #fff;
  border-color: #0052d9;
  box-shadow: 0 2px 8px rgba(0, 82, 217, 0.3);
}
.app-main {
  flex: 1;
  background: #f4f7fb;
}
</style>
