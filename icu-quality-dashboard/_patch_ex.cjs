import fs from "fs";
const p = "D:\\icu-quality-dashboard\\icu-quality-dashboard\\src\\utils\\exportExcel.js";
let c = fs.readFileSync(p, "utf8");

const oldPart = 'const headerRow = cols.map(c => c.header);\n  const dataRows = allRows.map(row => cols.map(c => c.get(row)));';
const newPart = [
  "const isExclusionSupported = code === 'ICU-08';",
  "const EXCL_REASON_MAP = {",
  "  non_ards: '非ARDS原因低氧', unstable_gas: '氧合数据非稳定状态',",
  "  contraindic: '存在俯卧位禁忌症', terminal: '终末期或家属放弃积极治疗',",
  "  data_error: 'PEEP或氧疗途径记录错误', other: '其他',",
  "};",
  "const exclHeaders = isExclusionSupported ? ['是否排除', '排除原因', '操作人', '排除时间'] : [];",
  "const headerRow = [...cols.map(c => c.header), ...exclHeaders];",
  "const dataRows = allRows.map(row => [...cols.map(c => c.get(row)), ...(isExclusionSupported ? [",
  "  row.excluded ? '是' : '否',",
  "  row.excluded ? (EXCL_REASON_MAP[row.reason_code] || row.reason_code || '') : '',",
  "  row.excluded ? (row.operator || '') : '',",
  "  row.excluded ? (row.excluded_at || '') : '',",
  "] : [])]);",
].join("\n  ");
c = c.replace(oldPart, newPart);
fs.writeFileSync(p, c, "utf8");
console.log("exportExcel.js updated");
