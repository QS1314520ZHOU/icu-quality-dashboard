<template>
  <div class="guide">
    <aside class="guide-nav">
      <button
        v-for="item in guides"
        :key="item.code"
        :class="{ active: item.code === activeCode }"
        @click="activeCode = item.code"
      >
        <span>{{ item.displayCode || displayCode(item.code) }}</span>
        <strong>{{ item.title }}</strong>
      </button>
    </aside>

    <section class="guide-body" v-if="active">
      <div class="hero">
        <span class="code">{{ active.displayCode || displayCode(active.code) }}</span>
        <div>
          <h2>{{ active.title }}</h2>
          <p>{{ active.source }}</p>
        </div>
      </div>

      <div class="formula-card">
        <div class="fraction">
          <div>{{ active.numerator }}</div>
          <span></span>
          <div>{{ active.denominator }}</div>
        </div>
        <strong>{{ multiplierText(active.code) }}</strong>
      </div>

      <div class="info-grid">
        <article>
          <label>分子口径</label>
          <p>{{ active.numerator }}</p>
        </article>
        <article>
          <label>分母口径</label>
          <p>{{ active.denominator }}</p>
        </article>
        <article class="wide">
          <label>计算规则</label>
          <p>{{ active.rule }}</p>
        </article>
        <article>
          <label>保留 / 纳入</label>
          <p>{{ active.include }}</p>
        </article>
        <article>
          <label>排除 / 去重</label>
          <p>{{ active.exclude }}</p>
        </article>
        <article>
          <label>去重口径</label>
          <p>{{ active.dedupe }}</p>
        </article>
        <article>
          <label>人工核查重点</label>
          <p>{{ active.audit }}</p>
        </article>
      </div>

      <div v-if="active.branches?.length" class="detail-section">
        <h3>分支判定口径</h3>
        <div class="branch-grid">
          <div v-for="b in active.branches" :key="b.name" class="branch-card">
            <strong>{{ b.name }}</strong>
            <p>{{ b.rule }}</p>
          </div>
        </div>
      </div>

      <div v-if="active.steps?.length" class="detail-section">
        <h3>系统判定步骤</h3>
        <ol>
          <li v-for="s in active.steps" :key="s">{{ s }}</li>
        </ol>
      </div>

      <div v-if="active.exclusions?.length" class="detail-section">
        <h3>明确排除情形</h3>
        <ul>
          <li v-for="e in active.exclusions" :key="e">{{ e }}</li>
        </ul>
      </div>

      <div class="note">
        系统来源：{{ active.systemSource }}
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue';
import { INDICATORS } from '../config/indicators.js';
import { getIndicatorGuide } from '../config/indicatorGuide.js';

const guides = getIndicatorGuide();
const activeCode = ref(guides[0]?.code || '');
const active = computed(() => guides.find(i => i.code === activeCode.value));

function displayCode(code) {
  return INDICATORS.find(i => i.code === code)?.displayCode || code;
}
function multiplierText(code) {
  const ind = INDICATORS.find(i => i.code === code);
  if (!ind) return '';
  if (ind.type === 'permille') return 'x 1000';
  if (ind.type === 'proportion' || ind.type === 'index') return '';
  return 'x 100%';
}
</script>

<style scoped>
.guide { display:grid; grid-template-columns:260px minmax(0,1fr); gap:18px; min-height:560px; }
.guide-nav { border-right:1px solid #e2e8f0; padding-right:12px; overflow:auto; max-height:68vh; }
.guide-nav button { width:100%; display:flex; gap:8px; align-items:center; text-align:left;
  background:#fff; border:1px solid transparent; border-radius:8px; padding:9px 10px; cursor:pointer;
  color:#334155; margin-bottom:5px; }
.guide-nav button:hover { background:#f8fafc; border-color:#dbeafe; }
.guide-nav button.active { background:#eff6ff; border-color:#93c5fd; color:#1d4ed8; }
.guide-nav span { flex-shrink:0; width:54px; font-size:12px; font-weight:800; color:#2563eb; }
.guide-nav strong { min-width:0; font-size:13px; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.guide-body { overflow:auto; max-height:68vh; padding-right:4px; }
.hero { display:flex; gap:14px; align-items:flex-start; background:linear-gradient(180deg,#f8fbff,#eef6ff);
  border:1px solid #dbeafe; border-radius:10px; padding:16px; margin-bottom:14px; }
.code { flex-shrink:0; background:#2563eb; color:#fff; border-radius:8px; padding:7px 10px;
  font-size:13px; font-weight:800; }
h2 { margin:0 0 6px; font-size:20px; color:#0f172a; letter-spacing:0; }
.hero p { margin:0; color:#475569; font-size:13px; line-height:1.7; }
.formula-card { display:flex; align-items:center; justify-content:center; gap:18px; background:#fff;
  border:1px solid #e2e8f0; border-radius:10px; padding:18px; margin-bottom:14px; }
.fraction { min-width:min(460px,100%); text-align:center; color:#1e293b; font-size:14px; line-height:1.6; }
.fraction span { display:block; height:1px; background:#334155; margin:7px 0; }
.formula-card strong { color:#2563eb; font-size:18px; }
.info-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
article { background:#fff; border:1px solid #e2e8f0; border-radius:10px; padding:13px 14px; }
article.wide { grid-column:1 / -1; }
label { display:block; color:#2563eb; font-size:12px; font-weight:800; margin-bottom:7px; }
article p { margin:0; color:#334155; font-size:13px; line-height:1.75; }
.detail-section { margin-top:14px; background:#fff; border:1px solid #e2e8f0; border-radius:10px; padding:14px 16px; }
.detail-section h3 { margin:0 0 10px; color:#1d4ed8; font-size:14px; }
.branch-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.branch-card { background:#f8fafc; border:1px solid #dbe4ef; border-radius:8px; padding:11px 12px; }
.branch-card strong { display:block; color:#0f172a; font-size:13px; margin-bottom:5px; }
.branch-card p { margin:0; color:#475569; font-size:13px; line-height:1.65; }
ol, ul { margin:0; padding-left:20px; color:#334155; font-size:13px; line-height:1.8; }
li + li { margin-top:4px; }
.note { margin-top:12px; color:#64748b; font-size:12px; line-height:1.7; background:#f8fafc;
  border:1px dashed #cbd5e1; border-radius:10px; padding:12px 14px; }
@media (max-width: 900px) {
  .guide { grid-template-columns:1fr; }
  .guide-nav { border-right:0; border-bottom:1px solid #e2e8f0; padding-right:0; padding-bottom:10px; max-height:220px; }
  .info-grid { grid-template-columns:1fr; }
  .branch-grid { grid-template-columns:1fr; }
}
</style>
