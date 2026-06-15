// src/api/index.js —— 对接 FastAPI 后端

const BASE = '/api';

// ---- 科室列表 ----
export async function fetchDepartments() {
  const res = await fetch(`${BASE}/departments`);
  return res.json();
}

// ---- 指标数据 ----
export async function fetchIndicators(start, end, dept = 'all', nocache = false) {
  const url = new URL(`${BASE}/indicators`, window.location.origin);
  url.searchParams.set('start', start);
  url.searchParams.set('end', end);
  url.searchParams.set('dept', dept);
  if (nocache) url.searchParams.set('_', Date.now());
  const res = await fetch(`${url.pathname}${url.search}`);
  return res.json();
}

// ---- 实时大屏指挥舱 ----
export async function fetchCommandCenter(period, endPeriod = '', icuUnit = 'all', nocache = false) {
  const url = new URL(`${BASE}/dashboard/command-center`, window.location.origin);
  url.searchParams.set('period', period);
  if (endPeriod) url.searchParams.set('end_period', endPeriod);
  url.searchParams.set('icu_unit', icuUnit);
  if (nocache) url.searchParams.set('_', Date.now());
  const res = await fetch(`${url.pathname}${url.search}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `大屏数据读取失败 (${res.status})`);
  }
  return res.json();
}

// ---- 指标明细列表（含分子/分母） ----
export async function fetchIndicatorList(period, icuUnit = 'all', endPeriod = '', nocache = false) {
  let url = `${BASE}/indicators/list?period=${period}&icu_unit=${encodeURIComponent(icuUnit)}`;
  if (endPeriod) url += `&end_period=${endPeriod}`;
  if (nocache) url += `&nocache=true`;
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
export async function fetchDetail(code, period, part, icuUnit = 'all', endPeriod = '', options = {}) {
  let url = `${BASE}/indicators/${code}/detail?period=${period}&part=${part}&icu_unit=${encodeURIComponent(icuUnit)}`;
  if (endPeriod) url += `&end_period=${endPeriod}`;
  if (options.limit) url += `&limit=${options.limit}`;
  if (options.offset) url += `&offset=${options.offset}`;
  if (['ICU-12', 'ICU-13'].includes(code)) url += '&nocache=true';
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

// ---- 手动刷新预聚合 ----
export async function triggerRefresh(deptCode, year, month, endMonth = month) {
  const params = new URLSearchParams();
  if (deptCode) params.set('dept_code', deptCode);
  if (year) params.set('year', year);
  if (month) params.set('month', month);
  const startPeriod = `${year}-${String(month).padStart(2, '0')}`;
  const endPeriod = `${year}-${String(endMonth).padStart(2, '0')}`;
  params.set('start_period', startPeriod);
  params.set('end_period', endPeriod);
  const res = await fetch(`${BASE}/refresh?${params.toString()}`, { method: 'POST' });
  if (res.status === 404) {
    const fallbackParams = new URLSearchParams();
    fallbackParams.set('dept', deptCode || 'all');
    fallbackParams.set('start_period', startPeriod);
    fallbackParams.set('end_period', endPeriod);

    const fallbackRes = await fetch(
      `${BASE}/admin/rebuild-summary?${fallbackParams.toString()}`,
      { method: 'POST' }
    );
    if (!fallbackRes.ok) {
      const err = await fallbackRes.json().catch(() => ({}));
      throw new Error(err.detail || `刷新请求失败 (${fallbackRes.status})`);
    }
    const stats = await fallbackRes.json();
    return {
      status: 'completed',
      immediate: true,
      stats,
      period: startPeriod,
    };
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `刷新请求失败 (${res.status})`);
  }
  return res.json();
}

export async function getRefreshStatus(taskId) {
  const res = await fetch(`${BASE}/refresh/${encodeURIComponent(taskId)}`);
  return res.json();
}
