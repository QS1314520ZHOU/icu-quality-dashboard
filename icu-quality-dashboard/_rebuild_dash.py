# -*- coding: utf-8 -*-
"""Rewrite Dashboard.vue - dark theme + all 3 files."""
import pathlib, re

BASE = pathlib.Path(r"D:\icu-quality-dashboard\icu-quality-dashboard\src")

def read(name):
    return (BASE / name).read_text(encoding="utf-8")

def write(name, text):
    (BASE / name).write_text(text, encoding="utf-8")
    print(f"  Wrote {name}: {len(text)} chars")

# ── Dashboard.vue ──
# Strategy: keep script section, replace template and style
dash = read("views/Dashboard.vue")
# Extract script
m = re.search(r'(<script setup>.*?</script>)', dash, re.DOTALL)
script_section = m.group(1)

new_template = '''<template>
  <div class="dashboard" data-theme="dark">
    <header class="db-header">
      <div class="db-header-left">
        <div class="db-brand">
          <span class="brand-cross">\u271a</span>
          <div>
            <span class="brand-name">ICU \u533b\u7597\u8d28\u91cf\u63a7\u5236\u4e2d\u5fc3</span>
            <span class="brand-sub">\u5b9e\u65f6\u5927\u5c4f\u770b\u677f</span>
          </div>
        </div>
      </div>
      <div class="db-header-right">
        <div class="filters">
          <select v-model.number="year" @change="loadData">
            <option v-for="y in years" :key="y" :value="y">{{ y }}\u5e74</option>
          </select>
          <select v-model.number="sMonth" @change="loadData">
            <option v-for="m in 12" :key="m" :value="m">{{ m }}\u6708</option>
          </select>
          <select v-model.number="eMonth" @change="loadData">
            <option v-for="m in 12" :key="m" :value="m">{{ m }}\u6708</option>
          </select>
          <select v-model="dept" @change="loadData">
            <option value="all">\u5168\u90e8ICU</option>
            <option v-for="d in departments" :key="d.code" :value="d.code">{{ d.name }}</option>
          </select>
        </div>
        <div class="header-actions">
          <button class="action-pill" @click="guideVisible=true">\u6307\u6807\u8bf4\u660e</button>
          <span class="status-pill" :class="risk.overall_status">\u72b6\u6001{{ overallText }}</span>
          <button class="action-pill icon-only" @click="loadData(true)" :disabled="loading">\U0001f504</button>
          <span v-if="updatedAt" class="meta-update">\u6700\u540e\u66f4\u65b0: {{ updatedAt }}</span>
        </div>
      </div>
    </header>

    <div v-if="error" class="state error">{{ error }}</div>
    <div v-else-if="loading" class="state">\u6b63\u5728\u8bfb\u53d6\u9884\u805a\u5408\u8d28\u63a7\u6570\u636e...</div>

    <!-- 6 KPI Stat Cards -->
    <section class="kpi-stats">
      <div class="kpi-stat-card" :class="risk.overall_status">
        <div class="kpi-card-left" :class="risk.overall_status"></div>
        <div class="kpi-card-body">
          <div class="kpi-card-top">
            <span class="kpi-card-label">\u5f02\u5e38\u98ce\u9669</span>
            <span class="kpi-card-icon">\u26a0\ufe0f</span>
          </div>
          <strong class="kpi-card-big" :class="risk.overall_status">{{ overallText }}</strong>
          <div class="kpi-card-delta">\u8f83\u6628\u65e5 <em :class="risk.counts?.danger > 0 ? \'up\' : \'flat\'">{{ risk.counts?.danger > 0 ? \'\u2191 \' + (risk.counts?.danger || 0) : '\u2014 0' }}</em></div>
          <span class="kpi-card-desc">{{ risk.headline || '\u5f02\u5e38\u4e8b\u4ef6\u9700\u5173\u6ce8\uff0c\u5efa\u8bae\u53ca\u65f6\u5904\u7406' }}</span>
        </div>
      </div>
      <div class="kpi-stat-card">
        <div class="kpi-card-left danger-accent"></div>
        <div class="kpi-card-body">
          <div class="kpi-card-top">
            <span class="kpi-card-label">\u4e25\u91cd\u5f02\u5e38\u6307\u6807</span>
            <span class="kpi-card-icon">\U0001f534</span>
          </div>
          <strong class="kpi-card-big">{{ risk.counts?.danger || 0 }}</strong>
          <div class="kpi-card-delta">\u8f83\u6628\u65e5 <em :class="(risk.counts?.danger||0)>0 ? \'up\' : \'flat\'">{{ (risk.counts?.danger||0)>0 ? \'\u2191 \' + risk.counts.danger : '\u2014 0' }}</em></div>
          <span class="kpi-card-desc">\u6d89\u53ca ICU \u5e8a\u533b\u6bd4\u3001ICU \u62a4\u58eb\u5e8a\u6bd4</span>
        </div>
      </div>
      <div class="kpi-stat-card">
        <div class="kpi-card-left warn-accent"></div>
        <div class="kpi-card-body">
          <div class="kpi-card-top">
            <span class="kpi-card-label">\u9884\u8b66\u6307\u6807</span>
            <span class="kpi-card-icon">\U0001f514</span>
          </div>
          <strong class="kpi-card-big">{{ risk.counts?.warn || 0 }}</strong>
          <div class="kpi-card-delta">\u8f83\u6628\u65e5 <em class="flat">\u2014 0</em></div>
          <span class="kpi-card-desc">\u6682\u65e0\u9884\u8b66\u6307\u6807</span>
        </div>
      </div>
      <div class="kpi-stat-card">
        <div class="kpi-card-left ai-accent"></div>
        <div class="kpi-card-body">
          <div class="kpi-card-top">
            <span class="kpi-card-label">AI \u603b\u7ed3</span>
            <span class="kpi-card-icon">\U0001f916</span>
          </div>
          <strong class="kpi-card-big">{{ aiTodoCount }}</strong>
          <div class="kpi-card-delta">\u8f83\u6628\u65e5 <em class="flat">\u2014 0</em></div>
          <span class="kpi-card-desc">AI\u672a\u8bc6\u522b\u5230\u9700\u91cd\u70b9\u5173\u6ce8\u95ee\u9898</span>
        </div>
      </div>
      <div class="kpi-stat-card">
        <div class="kpi-card-left sentinel-accent"></div>
        <div class="kpi-card-body">
          <div class="kpi-card-top">
            <span class="kpi-card-label">\u54e8\u5175\u4e8b\u4ef6</span>
            <span class="kpi-card-icon">\U0001f6e1\ufe0f</span>
          </div>
          <strong class="kpi-card-big">0</strong>
          <div class="kpi-card-delta">\u8f83\u6628\u65e5 <em class="flat">\u2014 0</em></div>
          <span class="kpi-card-desc">\u6682\u65e0\u54e8\u5175\u4e8b\u4ef6\u62a5\u544a</span>
        </div>
      </div>
      <div class="kpi-stat-card">
        <div class="kpi-card-left low-accent"></div>
        <div class="kpi-card-body">
          <div class="kpi-card-top">
            <span class="kpi-card-label">\u4f4e\u4ef7\u503c\u8bc4\u4f30</span>
            <span class="kpi-card-icon">\U0001f4ca</span>
          </div>
          <strong class="kpi-card-big">{{ ai.low_confidence?.count || 0 }}</strong>
          <div class="kpi-card-delta">\u8f83\u6628\u65e5 <em class="flat">\u2014 0</em></div>
          <span class="kpi-card-desc">\u6682\u65e0\u4f4e\u4ef7\u503c\u8bc4\u4f30\u9879\u76ee</span>
        </div>
      </div>
    </section>

    <div class="explain-bar">
      <span class="explain-main">{{ risk.explain || '\u5f02\u5e38\u548c\u9884\u8b66\u5747\u6309\u72b6\u6001\u914d\u7f6e\u4e2d\u7684\u9608\u503c\u5224\u5b9a\u3002' }}</span>
      <span class="explain-sub">{{ ai.explain || 'AI\u5f85\u529e\u4ec5\u4f5c\u8d28\u63a7\u7ebf\u7d22\u63d0\u793a\u3002' }}</span>
    </div>

    <section class="kpi-row">
      <div v-for="c in kpiList" :key="c.code" class="kpi-card" :class="c.status">
        <div class="kpi-top">
          <span class="kpi-code">{{ displayCode(c.code) }}</span>
          <span class="kpi-status">{{ statusText(c.status) }}</span>
        </div>
        <div class="kpi-name">{{ c.name }}</div>
        <div class="kpi-basis">{{ thresholdHint(c.code) }}</div>
        <div class="kpi-value">
          <span>{{ fmtValue(c.value) }}</span><small>{{ c.unit }}</small>
        </div>
        <div class="kpi-sub">\u5206\u5b50 {{ fmtCount(c.numerator) }} / \u5206\u6bcd {{ fmtCount(c.denominator) }}</div>
        <button class="kpi-guide" @click="guideVisible=true">\u53e3\u5f84\u8bf4\u660e</button>
      </div>
    </section>

    <!-- \u60a3\u8005\u52a8\u6001 KPI \u5361 -->
    <section v-if="censusData" class="census-strip">
      <div class="census-kpi">
        <span class="c-label">\u539f\u6709\u60a3\u8005</span>
        <strong>{{ censusData.carry_in }}</strong>
        <p>\u671f\u521d 0 \u70b9\u5df2\u5728\u79d1</p>
      </div>
      <div class="census-kpi">
        <span class="c-label">\u65b0\u5165\u60a3\u8005</span>
        <strong>{{ censusData.new_admit }}</strong>
        <p>\u7edf\u8ba1\u671f\u5185\u65b0\u5165</p>
      </div>
      <div class="census-kpi">
        <span class="c-label">\u51fa\u79d1\u60a3\u8005</span>
        <strong>{{ censusData.discharge }}</strong>
        <p>\u7edf\u8ba1\u671f\u5185\u51fa\u79d1</p>
      </div>
      <div class="census-kpi">
        <span class="c-label">\u671f\u672b\u5728\u79d1</span>
        <strong>{{ censusData.carry_out }}</strong>
        <p>\u539f\u6709 + \u65b0\u5165 - \u51fa\u79d1</p>
      </div>
      <div class="census-kpi">
        <span class="c-label">\u540c\u671f\u603b\u6570</span>
        <strong>{{ censusData.total }}</strong>
        <p>\u539f\u6709 + \u65b0\u5165</p>
      </div>
      <div class="census-kpi chart-kpi">
        <CensusStackChart :trend="censusTrend" />
      </div>
    </section>

    <section class="main-grid">
      <div class="panel abnormal-panel">
        <div class="panel-title"><span class="panel-icon">\u2630</span> \u5f02\u5e38\u6307\u6807\u6e05\u5355</div>
        <div v-if="abnormalList.length" class="abnormal-list">
          <div v-for="a in abnormalList" :key="a.code" class="abnormal-item" :class="a.status">
            <div class="ab-main">
              <span class="ab-code">{{ displayCode(a.code) }}</span>
              <strong>{{ a.name }}</strong>
              <span class="ab-status">{{ statusText(a.status) }}</span>
            </div>
            <div class="ab-meta">
              \u5f53\u524d {{ fmtValue(a.value) }}{{ a.unit }} \u00b7 \u5206\u5b50 {{ a.numerator ?? '/' }} / \u5206\u6bcd {{ a.denominator ?? '/' }}
              <span v-if="a.delta != null"> \u00b7 \u533a\u95f4\u53d8\u5316 {{ a.delta > 0 ? '+' : '' }}{{ a.delta }}</span>
            </div>
            <div class="ab-hint">{{ a.hint }}</div>
          </div>
        </div>
        <div v-else class="empty">\u5f53\u524d\u8303\u56f4\u5185\u6682\u65e0\u5f02\u5e38\u6216\u9884\u8b66\u6307\u6807\u3002</div>
      </div>

      <div class="panel ai-panel-wrap">
        <AiPanel :analysis="ai" />
      </div>

      <div class="panel">
        <div class="panel-title"><span class="panel-icon">\U0001f4c8</span> \u611f\u67d3\u53d1\u75c5\u7387\u76d1\u6d4b</div>
        <ControlChart name="VAP" :data="trendData[\'ICU-16\']" :months="months" :ucl="15" unit="\u2030" />
        <ControlChart name="CRBSI" :data="trendData[\'ICU-17\']" :months="months" :ucl="5" unit="\u2030" />
        <ControlChart name="CAUTI" :data="trendData[\'CAUTI\']" :months="months" :ucl="5" unit="\u2030" />
      </div>

      <div class="panel">
        <div class="panel-title"><span class="panel-icon">\u23f1</span> \u611f\u67d3\u6027\u4f11\u514b Bundle</div>
        <div class="bundle-row">
          <div v-for="b in bundleItems" :key="b.code" class="bundle-item" :class="b.status">
            <span>{{ b.label }}</span>
            <strong>{{ fmtValue(b.value) }}%</strong>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-title"><span class="panel-icon">\u25c9</span> \u91cd\u70b9\u6d41\u7a0b\u8fbe\u6807\u7387</div>
        <div class="gauge-grid">
          <GaugeChart v-for="g in processGauges" :key="g.code"
            :name="g.shortName" :value="g.value" :unit="g.unit" :status="g.status" />
        </div>
      </div>

      <div class="panel">
        <div class="panel-title"><span class="panel-icon">\U0001f465</span> \u4eba\u529b\u914d\u7f6e\u4e0e SMR</div>
        <BarTargetChart :items="ratioItems" />
        <SmrChart :current="smrCurrent" :history="smrHistory" :months="months" />
      </div>
    </section>

    <!-- \u5e95\u90e8\u514d\u8d23\u58f0\u660e -->
    <footer class="db-footer">
      <div class="footer-left">
        <span class="footer-icon">\u2139\ufe0f</span>
        \u6570\u636e\u6765\u6e90\uff1a\u533b\u9662\u4fe1\u606f\u7cfb\u7edf\uff08HIS\uff09| ICU\u8d28\u91cf\u7ba1\u7406\u7cfb\u7edf\uff08ICU-QMS\uff09
      </div>
      <div class="footer-right">
        <span class="footer-icon">\u2139\ufe0f</span>
        \u672c\u770b\u677f\u6570\u636e\u4ec5\u4f9b\u533b\u7597\u8d28\u91cf\u7ba1\u7406\u53c2\u8003\uff0c\u4e0d\u4f5c\u4e3a\u4e34\u5e8a\u51b3\u7b56\u4f9d\u636e
      </div>
    </footer>

    <Modal v-if="guideVisible" title="\u6307\u6807\u53e3\u5f84\u8bf4\u660e" @close="guideVisible=false">
      <IndicatorGuideModal />
    </Modal>
  </div>
</template>'''

new_style = '''<style scoped>
.dashboard {
  padding: 18px 24px 0;
  min-height: 100vh;
  background: #0b1120;
  color: #e2e8f0;
}
.db-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
  gap: 16px;
  flex-wrap: wrap;
}
.db-header-left { display: flex; align-items: center; gap: 16px; }
.db-brand { display: flex; align-items: center; gap: 10px; }
.brand-cross { font-size: 22px; color: var(--brand); }
.brand-name { display: block; font-size: 16px; font-weight: 700; color: #e2e8f0; }
.brand-sub { display: block; font-size: 12px; color: #94a3b8; margin-top: 2px; }
.db-header-right { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; justify-content: flex-end; }
.filters { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.filters select {
  background: #131c31; color: #e2e8f0; border: 1px solid #1e293b;
  border-radius: 6px; padding: 6px 10px; font-size: 13px;
}
.filters select:focus { border-color: var(--brand); outline: none; }
.header-actions { display: flex; align-items: center; gap: 8px; }
.action-pill {
  padding: 6px 14px; border-radius: 6px; border: 1px solid #1e293b;
  background: #131c31; color: #e2e8f0; font-size: 12px; cursor: pointer;
}
.action-pill:hover { background: #1a2540; border-color: var(--brand); }
.action-pill.icon-only { padding: 6px 10px; }
.action-pill:disabled { opacity: .5; cursor: not-allowed; }
.status-pill {
  padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: 600;
  background: rgba(44,142,137,0.15); color: var(--brand); border: 1px solid rgba(44,142,137,0.3);
}
.status-pill.danger { background: rgba(217,83,79,0.15); color: #D9534F; border-color: rgba(217,83,79,0.3); }
.status-pill.warn { background: rgba(232,165,61,0.15); color: #E8A53D; border-color: rgba(232,165,61,0.3); }
.meta-update { color: #64748b; font-size: 11px; white-space: nowrap; }

.state {
  margin-bottom: 12px; padding: 10px 12px; border-radius: 8px;
  background: rgba(44,142,137,0.1); color: #94a3b8; font-size: 13px;
  border: 1px solid rgba(44,142,137,0.2);
}
.state.error { background: rgba(217,83,79,0.1); color: #D9534F; border-color: rgba(217,83,79,0.2); }

/* KPI Stat Cards (top 6) */
.kpi-stats {
  display: grid; grid-template-columns: repeat(6, 1fr);
  gap: 12px; margin-bottom: 14px;
}
.kpi-stat-card {
  display: flex; background: #131c31; border: 1px solid #1e293b;
  border-radius: 10px; overflow: hidden; transition: transform .15s;
}
.kpi-stat-card:hover { transform: translateY(-2px); }
.kpi-card-left { width: 4px; flex-shrink: 0; background: #64748b; }
.kpi-card-left.danger-accent { background: #D9534F; }
.kpi-card-left.warn-accent { background: #E8A53D; }
.kpi-card-left.ai-accent { background: #6366f1; }
.kpi-card-left.sentinel-accent { background: #2C8E89; }
.kpi-card-left.low-accent { background: #94a3b8; }
.kpi-stat-card.danger .kpi-card-left { background: #D9534F; }
.kpi-stat-card.danger .kpi-card-big { color: #D9534F; }
.kpi-stat-card.warn .kpi-card-left { background: #E8A53D; }
.kpi-stat-card.warn .kpi-card-big { color: #E8A53D; }
.kpi-stat-card.good .kpi-card-left { background: #2C8E89; }
.kpi-card-body { padding: 12px 14px; flex: 1; min-width: 0; }
.kpi-card-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.kpi-card-label { font-size: 12px; color: #94a3b8; }
.kpi-card-icon { font-size: 16px; }
.kpi-card-big { display: block; font-size: 28px; color: #e2e8f0; margin-bottom: 4px; }
.kpi-card-delta { font-size: 11px; color: #64748b; margin-bottom: 4px; }
.kpi-card-delta em { font-style: normal; }
.kpi-card-delta em.up { color: #D9534F; }
.kpi-card-delta em.flat { color: #64748b; }
.kpi-card-desc { display: block; font-size: 11px; color: #475569; line-height: 1.4; }

/* Explain bar */
.explain-bar {
  margin: -2px 0 14px; color: #94a3b8; background: #131c31;
  border: 1px solid #1e293b; border-radius: 8px; padding: 10px 14px;
  font-size: 13px; line-height: 1.6;
}
.explain-main { color: #94a3b8; }
.explain-sub { display: block; color: #64748b; font-size: 12px; margin-top: 2px; }

/* KPI detail row */
.kpi-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px; }
.kpi-card {
  background: #131c31; border: 1px solid #1e293b;
  border-left: 4px solid #475569; border-radius: 10px; padding: 14px;
}
.kpi-card.good { border-left-color: #2C8E89; }
.kpi-card.warn { border-left-color: #E8A53D; }
.kpi-card.danger { border-left-color: #D9534F; }
.kpi-card.unknown { border-left-color: #475569; }
.kpi-top { display: flex; justify-content: space-between; gap: 8px; align-items: center; margin-bottom: 5px; }
.kpi-code { color: var(--brand); font-size: 12px; font-weight: 700; }
.kpi-status { color: #94a3b8; font-size: 12px; }
.kpi-name { color: #cbd5e1; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kpi-basis { margin-top: 5px; color: #64748b; font-size: 12px; line-height: 1.45; min-height: 18px; }
.kpi-value { margin-top: 6px; display: flex; align-items: baseline; gap: 3px; }
.kpi-value span { font-size: 26px; font-weight: 800; color: #e2e8f0; }
.kpi-value small { color: #64748b; }
.kpi-sub { margin-top: 4px; color: #64748b; font-size: 12px; }
.kpi-guide {
  margin-top: 8px; background: rgba(44,142,137,0.1);
  border: 1px solid rgba(44,142,137,0.3); border-radius: 6px;
  color: var(--brand); font-size: 12px; padding: 5px 8px; cursor: pointer;
}
.kpi-guide:hover { background: rgba(44,142,137,0.2); }

/* Census strip */
.census-strip { display: grid; grid-template-columns: repeat(4, 1fr) 2fr; gap: 10px; margin-bottom: 14px; }
.census-kpi { background: #131c31; border: 1px solid #1e293b; border-radius: 10px; padding: 12px 14px; }
.census-kpi .c-label { display: block; color: #94a3b8; font-size: 12px; margin-bottom: 5px; }
.census-kpi strong { font-size: 24px; color: #e2e8f0; }
.census-kpi p { margin: 6px 0 0; color: #64748b; font-size: 12px; line-height: 1.45; }
.census-kpi.chart-kpi { background: transparent; border: none; padding: 0; }

/* Main grid */
.main-grid { display: grid; grid-template-columns: 1.2fr 1fr 1fr; gap: 12px; }
.panel {
  background: #131c31; border: 1px solid #1e293b; border-radius: 10px;
  padding: 14px 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.2); min-width: 0;
}
.panel-title {
  font-size: 14px; color: var(--brand); font-weight: 700;
  margin-bottom: 12px; padding-left: 8px; border-left: 3px solid var(--brand);
  display: flex; align-items: center; gap: 6px;
}
.panel-icon { font-size: 14px; opacity: .7; }
.abnormal-panel { grid-row: span 2; }
.ai-panel-wrap { grid-row: span 2; }
.abnormal-list { display: flex; flex-direction: column; gap: 8px; max-height: 560px; overflow: auto; padding-right: 2px; }
.abnormal-item {
  border: 1px solid #1e293b; border-radius: 8px; padding: 12px;
  background: #0f1729; transition: background .15s;
}
.abnormal-item:hover { background: #1a2540; }
.abnormal-item.danger { background: rgba(217,83,79,0.06); border-color: rgba(217,83,79,0.25); }
.abnormal-item.warn { background: rgba(232,165,61,0.06); border-color: rgba(232,165,61,0.25); }
.ab-main { display: flex; align-items: center; gap: 8px; min-width: 0; }
.ab-code { color: var(--brand); font-weight: 700; font-size: 12px; }
.ab-main strong { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; color: #e2e8f0; }
.ab-status { font-size: 12px; color: #94a3b8; }
.ab-meta { margin-top: 6px; color: #64748b; font-size: 12px; line-height: 1.5; }
.ab-hint { margin-top: 5px; color: #94a3b8; font-size: 12px; line-height: 1.5; }
.empty {
  color: #475569; font-size: 13px; padding: 20px; text-align: center;
  background: #0f1729; border: 1px dashed #1e293b; border-radius: 8px;
}
.bundle-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; padding: 8px 0; }
.bundle-item {
  border: 1px solid #1e293b; border-radius: 8px;
  padding: 16px 12px; text-align: center; background: #0f1729;
}
.bundle-item span { display: block; color: #94a3b8; font-size: 13px; margin-bottom: 6px; }
.bundle-item strong { font-size: 26px; color: #e2e8f0; }
.bundle-item.good strong { color: #2C8E89; }
.bundle-item.warn strong { color: #E8A53D; }
.bundle-item.danger strong { color: #D9534F; }
.gauge-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 4px; }

/* Footer disclaimer */
.db-footer {
  display: flex; justify-content: space-between; align-items: center;
  margin-top: 16px; padding: 12px 16px; background: #0f1729;
  border: 1px solid #1e293b; border-radius: 8px; font-size: 12px; color: #64748b;
}
.footer-icon { margin-right: 4px; }

@media (max-width: 1200px) {
  .kpi-stats { grid-template-columns: repeat(3, 1fr); }
  .kpi-row { grid-template-columns: repeat(2, 1fr); }
  .main-grid { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .kpi-stats { grid-template-columns: repeat(2, 1fr); }
  .db-header { flex-direction: column; }
  .db-header-right { width: 100%; }
}
</style>'''

# Reassemble
m_style = re.search(r'(<style scoped>.*?</style>)', dash, re.DOTALL)
m_tmpl = re.search(r'(<template>.*?</template>)', dash, re.DOTALL)

dash_new = dash[:m_tmpl.start()] + new_template + '\n\n' + script_section + '\n\n' + new_style + '\n'
write("views/Dashboard.vue", dash_new)
print("Dashboard.vue done")

