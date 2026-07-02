// src/utils/detailColumns.js
// ============================================================
// 指标明细「单一数据源」列定义
// DetailModal.vue（渲染表头/单元格）与 exportExcel.js（导出）共同调用，
// 保证界面展示与 Excel 导出永远一致。
//
// 每列结构：{ header: string, get: (patient) => string }
//   - header：中文表头（表格 <thead> 与 Excel 首行都用它）
//   - get   ：返回「已格式化」的显示文本（日期/布尔/空值均已处理）
// ============================================================

/* ---------------- 统一格式化 ---------------- */

export function fmtDate(v) {
  if (v === null || v === undefined || v === '') return ''
  const d = v instanceof Date ? v : new Date(v)
  if (isNaN(d.getTime())) return String(v) // 非日期：原样返回，不猜
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export function fmtBool(v) {
  if (v === true) return '是'
  if (v === false) return '否'
  return v == null ? '' : String(v)
}

export function fmtText(v) {
  return v == null ? '' : String(v)
}

/* ---------------- 指标分组（与 DetailModal.vue 模板分支一一对应）---------------- */

const AIRWAY_CODES = ['ICU-12', 'ICU-13']
const TRITUBE_CODES = ['ICU-16', 'ICU-17', 'CAUTI']
const ASSESSMENT_CODES = ['ICU-09', 'ICU-10']

/* ---------------- 通用列片段 ---------------- */

const COL_PATIENT_ID = { header: '住院号', get: (p) => fmtText(p.patient_id) }
const COL_NAME       = { header: '姓名',   get: (p) => fmtText(p.name) }

/* ============================================================
 * default 分支 col3/col4/col5 中文表头 —— 按 code + part 决定
 * 来源：DetailModal.vue L227-262 col3/col4/col5 computed
 * ============================================================ */

function isStaffCode(code) { return code === 'ICU-02' || code === 'ICU-03' }

function resolveCol3Header(code, part) {
  if (isStaffCode(code)) return '职称'
  if (code === 'ICU-08' && part === 'denominator') return 'P/F  PEEP'
  if (code === 'ICU-08' && part === 'numerator') return '俯卧次数'
  if (code === 'ICU-06' && part === 'denominator') return '抗菌药 [目的]'
  if (code === 'ICU-06' && part === 'numerator') return '送检项目'
  if (code === 'ICU-07' && part === 'numerator') return '预防措施'
  if (code === 'ICU-11') return '转归'
  if (code === 'ICU-13' && part === 'numerator') return '拔管→再置管'
  if (code === 'ICU-12' || code === 'ICU-13') return '管道类型'
  return '床号'
}

function resolveCol4Header(code, part) {
  if (isStaffCode(code)) return '入职日期'
  if (code === 'ICU-08' && part === 'denominator') return '纳入路径'
  if (code === 'ICU-08' && part === 'numerator') return '首次俯卧时间'
  if (code === 'ICU-06' && part === 'denominator') return '给药 & 判定理由'
  if (code === 'ICU-06' && part === 'numerator') return '送检时间'
  if (code === 'ICU-07' && part === 'numerator') return '医嘱示例'
  if (code === 'ICU-11') return '首次APACHEⅡ时间'
  if (code === 'ICU-13' && part === 'numerator') return '拔管/再置管时间'
  if (code === 'ICU-12' || code === 'ICU-13') return '拔管时间'
  return '入科时间'
}

function resolveCol5Header(code, part) {
  if (isStaffCode(code)) return '人数'
  if (code === 'ICU-08' && part === 'denominator') return 'P/F值'
  if (code === 'ICU-08' && part === 'numerator') return '俯卧总次数'
  if (code === 'ICU-04' && part === 'numerator') return 'APACHEⅡ'
  if (code === 'ICU-04' && part === 'denominator') return '在科'
  if (code === 'ICU-01' && part === 'numerator') return '在床天数'
  if (code === 'ICU-06' && part === 'denominator') return '给药次数'
  if (code === 'ICU-07' && part === 'numerator') return '医嘱条数'
  if (code === 'ICU-11') return '预计死亡率'
  if (code === 'ICU-12' || code === 'ICU-13') return '例次'
  return '数值'
}

function resolveDefaultCols(code, part) {
  return [
    { header: resolveCol3Header(code, part), get: (p) => fmtText(p.bed_no) },
    { header: resolveCol4Header(code, part), get: (p) => fmtDate(p.admit_time) },
    { header: resolveCol5Header(code, part), get: (p) => fmtText(p.value ?? '—') },
  ]
}

/* ============================================================
 * ICU-12/13 气道动态列
 * 来源：DetailModal.vue L182-193 airwayExtraCol / airwayExtraValue
 * ============================================================ */

function airwayExtraHeader(code, part) {
  if (code === 'ICU-13' && part === 'numerator') return '再置管'
  if (code === 'ICU-12' && part === 'numerator') return '非计划'
  return '说明'
}

function airwayExtraGet(code, part) {
  return (p) => {
    if (code === 'ICU-13' && part === 'numerator') {
      return p.reinsert_start ? `${p.reinsert_type} ${p.reinsert_start}` : ''
    }
    if (code === 'ICU-12' && part === 'numerator') return p.unplanned ? '是' : '否'
    return ''
  }
}

/* ============================================================
 * ICU-19 动态列
 * 来源：DetailModal.vue L219-225 icu19TimeCol/icu19SourceCol/icu19EvidenceCol/icu19Evidence
 * ============================================================ */

function resolveIcu19Cols(part) {
  const timeHeader = part === 'numerator' ? 'EN启动时间' : 'EN启动情况'
  const sourceHeader = part === 'numerator' ? '启动来源' : '判定来源'
  const evidenceHeader = part === 'numerator' ? '命中证据' : '命中/禁忌证'

  return {
    timeHeader,
    timeGet: (p) =>
      part === 'numerator'
        ? fmtText(p.enStartTime || p.discharge_time || '/')
        : fmtText(p.windowResult || p.admission_source || '/'),
    sourceHeader,
    sourceGet: (p) => fmtText(p.enSource || p.bed_no || '/'),
    evidenceHeader,
    evidenceGet: (p) => {
      const hit = p.enHit || p.enRoute || p.enDrug || '/'
      return p.contraindication ? `${hit}；禁忌证：${p.contraindication}` : hit
    },
  }
}

/* ============================================================
 * ICU-16/17/CAUTI 三管卡片→列
 * 来源：DetailModal.vue L194-218 triTubeCol3/4/5 + triTubeValue3/4/5 + triTubeTimeText
 * ============================================================ */

function resolveTriTubeCols(code, part) {
  const col3Header = part === 'numerator' ? '感染类型' : '设备/导管'
  const col4Header = part === 'numerator' ? '诊断时间' : '天数'
  let col5Header = '备注'
  if (part === 'denominator') {
    col5Header = code === 'ICU-16' ? '通气方式 / 记录点数' : '管道类型 / 置管点数'
  }

  return {
    col3Header,
    col3Get: (p) =>
      part === 'numerator'
        ? fmtText(p.diseaseType || p.bed_no || '/')
        : fmtText(p.device_type || p.bed_no || '/'),
    col4Header,
    col4Get: (p) =>
      part === 'numerator'
        ? fmtText(p.diagnosisTime || p.admit_time || '/')
        : (p.device_days ? `${p.device_days}天` : p.admit_time ? `${p.admit_time}天` : '/'),
    col5Header,
    col5Get: (p) => {
      if (part === 'numerator') return fmtText(p.notes || p.dept || '/')
      return `${fmtText(p.tube_type || p.device_value || p.dept || '/')} / ${p.tube_points || 0}`
    },
    timeGet: (p) => {
      if (part === 'numerator') return fmtText(p.diagnosisTime || p.admit_time || '')
      const parts = []
      if (p.device_day) parts.push(`日期：${p.device_day}`)
      if (p.tube_start) parts.push(`开始：${p.tube_start}`)
      if (p.tube_end) parts.push(`结束：${p.tube_end}`)
      return parts.join('  ')
    },
  }
}

/* ============================================================
 * 主入口：getDetailColumns(code, part)
 * part: 'numerator' | 'denominator'
 * 返回：[{ header, get }]
 * ============================================================ */

export function getDetailColumns(code, part) {
  // ---- ICU-15：转出ICU后48h重返率 ----
  if (code === 'ICU-15') {
    return [
      COL_PATIENT_ID,
      COL_NAME,
      { header: '出科时间',     get: (p) => fmtText(p.icuDischargeTime || p.admit_time || '/') },
      { header: '重返入科时间', get: (p) => fmtText(p.reIcuAdmissionTime || p.discharge_time || '/') },
      { header: '来源',         get: (p) => fmtText(p.event_source || p.admission_source || '/') },
      { header: '依据',         get: (p) => fmtText(p.basis || '/') },
    ]
  }

  // ---- ICU-18：急性脑损伤意识评估率 ----
  if (code === 'ICU-18') {
    return [
      COL_PATIENT_ID,
      COL_NAME,
      { header: '脑损伤类别', get: (p) => fmtText(p.brain_category || p.bed_no || '/') },
      { header: '入分母来源', get: (p) => fmtText(p.den_source || p.dept || '/') },
      { header: '命中依据',   get: (p) => fmtText(p.evidence || p.basis || '/') },
      { header: '是否评估',   get: (p) => fmtText(p.assessed || '/') },
      { header: '首次评估',   get: (p) => {
        const t = fmtText(p.firstAssessTime || p.discharge_time || '/')
        const s = fmtText(p.assessSource || '')
        return s ? `${t} ${s}` : t
      }},
    ]
  }

  // ---- ICU-14：非计划转入ICU ----
  if (code === 'ICU-14') {
    return [
      COL_PATIENT_ID,
      COL_NAME,
      { header: '转入类型',    get: (p) => fmtText(p.admissionType || p.bed_no) },
      { header: '转入计划',    get: (p) => fmtText(p.admissionPlan || p.admission_source || '/') },
      { header: '手术名称',    get: (p) => fmtText(p.operation_name || p.dept || '/') },
      { header: '转入ICU时间', get: (p) => fmtText(p.icuAdmissionTime || p.admit_time) },
      { header: '依据',        get: (p) => fmtText(p.basis || '/') },
    ]
  }

  // ---- ICU-12/13：气道/管道 ----
  if (AIRWAY_CODES.includes(code)) {
    return [
      COL_PATIENT_ID,
      COL_NAME,
      { header: '管道类型', get: (p) => fmtText(p.tube_type) },
      { header: '插管时间', get: (p) => fmtDate(p.tube_start) },
      { header: '拔管时间', get: (p) => fmtDate(p.tube_end) },
      { header: airwayExtraHeader(code, part), get: airwayExtraGet(code, part) },
      { header: '例次',     get: () => '1' },
    ]
  }

  // ---- ICU-19：48h 内 EN 启动率（动态列，按 part）----
  if (code === 'ICU-19') {
    const d = resolveIcu19Cols(part)
    return [
      COL_PATIENT_ID,
      COL_NAME,
      { header: '入科时间',       get: (p) => fmtText(p.icuAdmissionTime || p.admit_time || '/') },
      { header: d.timeHeader,     get: d.timeGet },
      { header: d.sourceHeader,   get: d.sourceGet },
      { header: d.evidenceHeader, get: d.evidenceGet },
      { header: '判定说明',       get: (p) => fmtText(p.basis || '/') },
    ]
  }

  // ---- ICU-16/17/CAUTI：三管（卡片→列）----
  if (TRITUBE_CODES.includes(code)) {
    const t = resolveTriTubeCols(code, part)
    return [
      COL_PATIENT_ID,
      COL_NAME,
      { header: t.col3Header, get: t.col3Get },
      { header: t.col4Header, get: t.col4Get },
      { header: t.col5Header, get: t.col5Get },
      { header: '时间',       get: t.timeGet },
      { header: '依据',       get: (p) => fmtText(p.basis || p.admission_source || '/') },
    ]
  }

  // ---- ICU-09/10 分子：评估类 ----
  if (ASSESSMENT_CODES.includes(code) && part === 'numerator') {
    return [
      COL_PATIENT_ID,
      COL_NAME,
      { header: '评估来源',   get: (p) => fmtText(p.bed_no) },
      { header: '评分中文名', get: (p) => fmtText(p.dept) },
      { header: '分值',       get: (p) => fmtText(p.value ?? '—') },
      { header: '评估时间',   get: (p) => fmtDate(p.admit_time) },
    ]
  }

  // ---- default（ICU-01~08、11 及 09/10 分母等）----
  const dyn = resolveDefaultCols(code, part)
  return [
    COL_PATIENT_ID,
    COL_NAME,
    ...dyn,
  ]
}
