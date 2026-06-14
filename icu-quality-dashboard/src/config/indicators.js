// src/config/indicators.js
// 指标类型: ratio(百分率) / permille(千分率) / proportion(配比) / index(指数)
// thresholds: 红黄绿阈值, direction: higher_better / lower_better

export const INDICATORS = [
  {
    code: 'ICU-01', name: 'ICU床位使用率', type: 'ratio', unit: '%',
    numerator: '实际占用总床日数', denominator: '实际开放总床日数',
    multiplier: 100, direction: 'range', // 床位使用率太高太低都不好
    thresholds: { good: [75, 85], warn: [60, 95], }, // 75-85%为佳
    meaning: '反映重症床位资源使用效率', chart: 'gauge',
  },
  {
    code: 'ICU-02', name: 'ICU医师床位比', type: 'proportion', unit: ':1',
    numerator: 'ICU医师总数', denominator: '实际开放床位数',
    multiplier: 1, direction: 'higher_better',
    thresholds: { good: [0.8, 99], warn: [0.5, 99] }, // ≥0.8:1
    meaning: '反映ICU人力资源配置', chart: 'bar',
  },
  {
    code: 'ICU-03', name: 'ICU护士床位比', type: 'proportion', unit: ':1',
    numerator: 'ICU护士总数', denominator: '实际开放床位数',
    multiplier: 1, direction: 'higher_better',
    thresholds: { good: [2.5, 99], warn: [2, 99] }, // ≥2.5:1
    meaning: '反映ICU人力资源配置', chart: 'bar',
  },
  {
    code: 'ICU-04', name: 'APACHEⅡ≥15分收治率', type: 'ratio', unit: '%',
    numerator: '首次APACHEⅡ≥15分患者数', denominator: '同期收治患者总数',
    multiplier: 100, direction: 'higher_better',
    thresholds: { good: [50, 100], warn: [30, 100] },
    meaning: '反映收治患者病情危重程度', chart: 'gauge',
  },
  {
    code: 'ICU-05', name: '感染性休克bundle完成率', type: 'ratio', unit: '%',
    numerator: '完成bundle患者数', denominator: '确诊感染性休克患者数',
    multiplier: 100, direction: 'higher_better',
    subMetrics: ['1h', '3h', '6h'], // ★需分时段计算
    thresholds: { good: [90, 100], warn: [70, 100] },
    meaning: '反映成人感染性休克治疗规范性', chart: 'trend',
    formulaDetail: {
      type: 'note',
      note: '分子=完成bundle患者数，分母=确诊感染性休克患者数，可分别计算1h/3h/6h完成率',
    },
  },
  {
    code: 'ICU-06', name: '抗菌药物治疗前病原学送检率', type: 'ratio', unit: '%',
    numerator: '用药前送检患者数', denominator: '治疗性用药患者总数',
    multiplier: 100, direction: 'higher_better',
    thresholds: { good: [90, 100], warn: [50, 100] },
    meaning: '反映抗菌药物使用规范性', chart: 'gauge',
  },
  {
    code: 'ICU-07', name: 'DVT预防率', type: 'ratio', unit: '%',
    numerator: '进行DVT预防患者数', denominator: '同期患者总数',
    multiplier: 100, direction: 'higher_better',
    thresholds: { good: [85, 100], warn: [60, 100] },
    meaning: '反映DVT预防情况', chart: 'gauge',
  },
  {
    code: 'ICU-08', name: '中重度ARDS俯卧位通气实施率', type: 'ratio', unit: '%',
    numerator: '实施俯卧位通气人数', denominator: '应实施人数(PEEP≥5,OI≤150)',
    multiplier: 100, direction: 'higher_better',
    thresholds: { good: [80, 100], warn: [50, 100] },
    meaning: '反映ARDS规范治疗', chart: 'gauge',
  },
  {
    code: 'ICU-09', name: 'ICU镇痛评估率', type: 'ratio', unit: '%',
    numerator: '镇痛评估患者数(NRS/CPOT/BPS)', denominator: '同期患者总数',
    multiplier: 100, direction: 'higher_better',
    thresholds: { good: [90, 100], warn: [70, 100] },
    meaning: '反映镇痛评估情况', chart: 'gauge',
  },
  {
    code: 'ICU-10', name: 'ICU镇静评估率', type: 'ratio', unit: '%',
    numerator: '镇静评估患者数(RASS/SAS)', denominator: '同期患者总数',
    multiplier: 100, direction: 'higher_better',
    thresholds: { good: [90, 100], warn: [70, 100] },
    meaning: '反映镇静评估情况', chart: 'gauge',
  },
  {
    code: 'ICU-11', name: 'ICU患者标化病死指数', type: 'index', unit: '',
    numerator: '实际病死率', denominator: '预计病死率',
    multiplier: 1, direction: 'lower_better', // <1说明优于预期
    customCalc: 'smr', // ★走自定义计算器
    thresholds: { good: [0, 1], warn: [0, 1.2] },
    meaning: '反映ICU整体诊疗水平', chart: 'gauge',
    formulaDetail: {
      type: 'special',
      lines: [
        '标化病死指数 = 实际病死率 ÷ 预计病死率',
        '预计病死率 = Σ每位患者首次APACHEⅡ预计病死率 ÷ 收治总数',
        '实际病死率 = 实际死亡人数 ÷ 收治总数',
      ],
    },
  },
  {
    code: 'ICU-12', name: '非计划气管插管拔管率', type: 'ratio', unit: '%',
    numerator: '非计划拔管例数', denominator: '拔管总例数',
    multiplier: 100, direction: 'lower_better',
    thresholds: { good: [0, 5], warn: [0, 10] },
    meaning: '反映ICU管理水平', chart: 'gauge',
  },
  {
    code: 'ICU-13', name: '拔管后48h再插管率', type: 'ratio', unit: '%',
    numerator: '48h内再插管例数', denominator: '拔管总例数',
    multiplier: 100, direction: 'lower_better',
    thresholds: { good: [0, 5], warn: [0, 12] },
    meaning: '反映脱机拔管指征把握能力', chart: 'gauge',
  },
  {
    code: 'ICU-14', name: '非计划转入ICU率', type: 'ratio', unit: '%',
    numerator: '非计划转入手术患者数', denominator: '转入ICU手术患者总数',
    multiplier: 100, direction: 'lower_better',
    thresholds: { good: [0, 5], warn: [0, 10] },
    meaning: '反映医疗质量重要结果指标', chart: 'gauge',
  },
  {
    code: 'ICU-15', name: '转出ICU后48h重返率', type: 'ratio', unit: '%',
    numerator: '48h内重返ICU患者数', denominator: '转出ICU患者总数',
    multiplier: 100, direction: 'lower_better',
    thresholds: { good: [0, 3], warn: [0, 6] },
    meaning: '反映转出指征把握能力', chart: 'gauge',
  },
  {
    code: 'ICU-16', name: 'VAP发病率', type: 'permille', unit: '‰',
    numerator: 'VAP新发例次', denominator: '有创呼吸机累计使用天数',
    multiplier: 1000, direction: 'lower_better',
    thresholds: { good: [0, 8], warn: [0, 15] },
    meaning: '反映感控及机械通气管理能力', chart: 'control',
  },
  {
    code: 'ICU-17', name: 'CRBSI发病率', type: 'permille', unit: '‰',
    numerator: 'CRBSI新发例次', denominator: '血管导管累计使用天数',
    multiplier: 1000, direction: 'lower_better',
    thresholds: { good: [0, 2], warn: [0, 5] },
    meaning: '反映感控及导管留置管理能力', chart: 'control',
  },
  {
    code: 'ICU-18', name: '急性脑损伤意识评估率', type: 'ratio', unit: '%',
    numerator: '完成意识评估患者数(GCS/FOUR)', denominator: '急性脑损伤患者总数',
    multiplier: 100, direction: 'higher_better',
    thresholds: { good: [90, 100], warn: [70, 100] },
    meaning: '反映脑损伤患者评估规范性', chart: 'gauge',
  },
  {
    code: 'ICU-19', name: '48h内肠内营养启动率', type: 'ratio', unit: '%',
    numerator: '48h内启动EN患者数', denominator: '入住>48h患者总数',
    multiplier: 100, direction: 'higher_better',
    thresholds: { good: [80, 100], warn: [50, 100] },
    meaning: '反映营养治疗规范性', chart: 'gauge',
  },
];

// 阈值判定 -> 返回 'good' | 'warn' | 'danger'
export function evalStatus(indicator, value) {
  const { good, warn } = indicator.thresholds;
  const inRange = (v, [a, b]) => v >= a && v <= b;
  if (inRange(value, good)) return 'good';
  if (inRange(value, warn)) return 'warn';
  return 'danger';
}
