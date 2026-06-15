// src/api/index.js —— 对接 FastAPI 后端

const BASE = '/api';

// ---- 科室列表 ----
export async function fetchDepartments() {
  const res = await fetch(`${BASE}/departments`);
  return res.json();
}

// ---- 指标数据 ----
export async function fetchIndicators(start, end, dept = 'all') {
  const res = await fetch(
    `${BASE}/indicators?start=${start}&end=${end}&dept=${encodeURIComponent(dept)}`
  );
  return res.json();
}

// ---- 指标明细列表（含分子/分母） ----
export async function fetchIndicatorList(period, icuUnit = 'all', endPeriod = '') {
  let url = `${BASE}/indicators/list?period=${period}&icu_unit=${encodeURIComponent(icuUnit)}`;
  if (endPeriod) url += `&end_period=${endPeriod}`;
  const res = await fetch(url);
  return res.json();
}

// ---- 单指标趋势 ----
export async function fetchTrend(code, year, icuUnit = 'all', sMonth = 1, eMonth = 12) {
  let url = `${BASE}/indicators/${code}/trend?year=${year}&icu_unit=${encodeURIComponent(icuUnit)}`;
  if (sMonth > 1 || eMonth < 12) url += `&start_month=${sMonth}&end_month=${eMonth}`;
  const res = await fetch(url);
  return res.json();
}

// ---- 分子/分母下钻明细 ----
export async function fetchDetail(code, period, part, icuUnit = 'all', endPeriod = '') {
  let url = `${BASE}/indicators/${code}/detail?period=${period}&part=${part}&icu_unit=${encodeURIComponent(icuUnit)}`;
  if (endPeriod) url += `&end_period=${endPeriod}`;
  const res = await fetch(url);
  return res.json();
}

// ---- AI 分析 ----
export async function fetchAiAnalysis(indicators, period) {
  const res = await fetch(`${BASE}/ai/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ indicators, period }),
  });
  return res.json();
}

// ---- ICU-06 AI 决策复核 ----
export async function fetchAiDecisions(params = {}) {
  const qs = new URLSearchParams();
  if (params.period_start) qs.set('period_start', params.period_start);
  if (params.period_end) qs.set('period_end', params.period_end);
  if (params.min_confidence != null) qs.set('min_confidence', params.min_confidence);
  if (params.limit) qs.set('limit', params.limit);
  const url = `${BASE}/ai-decisions?${qs.toString()}`;
  const res = await fetch(url);
  return res.json();
}

export async function overrideAiDecision(hisPid, purpose, reason, overriddenBy = '主任') {
  const res = await fetch(`${BASE}/ai-decisions/override`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ hisPid, purpose, reason, overridden_by: overriddenBy }),
  });
  return res.json();
}
