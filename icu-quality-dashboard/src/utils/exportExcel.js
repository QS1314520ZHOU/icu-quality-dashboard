/**
 * exportExcel.js — 明细导出 Excel 工具
 *
 * 纯前端方案：xlsx (SheetJS Community) 动态懒加载，UTF-8 中文无乱码。
 * 全量拉取 + 护栏（最大 5000 条、进度回调、失败报错）。
 * 列定义复用 detailColumns.js 共享模块，与界面展示完全一致。
 */

import { getDetailColumns } from './detailColumns.js';
import { fetchDetail } from '../api/index.js';

const MAX_ROWS = 5000;
const PAGE_SIZE = 500;

/**
 * 文件名净化：移除 Windows/Unix 非法字符
 */
function sanitizeFilename(s) {
  return (s || '').replace(/[\\/:*?"<>|]/g, '_').replace(/\s+/g, '_');
}

/**
 * 导出明细 Excel
 *
 * @param {Object} opts
 * @param {string} opts.code - 指标编码
 * @param {string} opts.name - 指标名
 * @param {string} opts.part - 'numerator' | 'denominator'
 * @param {string} opts.period - 统计期 e.g. '2026-06'
 * @param {string} [opts.endPeriod] - 多月统计的结束期
 * @param {string} opts.unit - 科室编码
 * @param {string} opts.unitName - 科室显示名
 * @param {string} [opts.sourceDesc] - 口径描述
 * @param {Array} [opts.patients] - 已加载的首屏数据（可复用）
 * @param {boolean} [opts.hasMore] - 是否还有更多数据
 * @param {Function} [opts.onProgress] - 进度回调 (loaded, total) => void
 * @returns {Promise<void>}
 */
export async function exportDetailExcel(opts) {
  const {
    code, name, part, period, endPeriod = '',
    unit, unitName = '',
    sourceDesc = '',
    patients: firstPage = [],
    hasMore = false,
    onProgress,
  } = opts;

  // ── 1. 懒加载 xlsx ──
  const XLSX = await import('xlsx');

  // ── 2. 全量数据拉取 ──
  let allRows = [...firstPage];

  if (hasMore && firstPage.length > 0) {
    let offset = firstPage.length;
    let rounds = 0;
    const maxRounds = Math.ceil(MAX_ROWS / PAGE_SIZE);

    while (rounds < maxRounds) {
      rounds++;
      if (onProgress) onProgress(allRows.length, null);

      let resp;
      try {
        resp = await fetchDetail(code, period, part, unit, endPeriod, {
          limit: PAGE_SIZE,
          offset,
        });
      } catch (e) {
        throw new Error(`第 ${rounds} 页拉取失败(offset=${offset}): ${e.message || e}`);
      }

      const batch = resp.patients || [];
      allRows = allRows.concat(batch);

      if (allRows.length >= MAX_ROWS) {
        console.warn(`[exportExcel] 达到上限 ${MAX_ROWS} 条，截断导出`);
        break;
      }
      if (!resp.has_more || batch.length === 0) break;

      offset += batch.length;
    }
  }

  if (allRows.length === 0) {
    throw new Error('无可导出数据');
  }

  // ── 3. 共享列定义（与界面完全一致）──
  const cols = getDetailColumns(code, part);

  // ── 4. 构建 worksheet ──
  const partLabel = part === 'numerator' ? '分子' : '分母';
  const startStr = period;
  const endStr = endPeriod || period;
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const exportTime = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`;

  const metaRows = [
    [`指标编码：${code}　　指标名：${name}`],
    [`科室：${unitName || unit}　　统计周期：${startStr} ~ ${endStr}`],
    [`口径：${partLabel}${sourceDesc ? '　　' + sourceDesc : ''}`],
    [`导出时间：${exportTime}`],
    [`共 ${allRows.length} 条记录`],
    [],  // 空行
  ];

  const headerRow = cols.map(c => c.header);
  const dataRows = allRows.map(row => cols.map(c => c.get(row)));

  const aoa = [...metaRows, headerRow, ...dataRows];
  const ws = XLSX.utils.aoa_to_sheet(aoa);

  // 设置列宽（按表头字数和内容估算）
  ws['!cols'] = cols.map((c, i) => {
    const headerLen = (c.header || '').length * 2; // 中文字符宽
    let maxLen = headerLen;
    for (let r = 0; r < Math.min(20, dataRows.length); r++) {
      const cellLen = String(dataRows[r][i] || '').length;
      if (cellLen > maxLen) maxLen = cellLen;
    }
    return { wch: Math.min(Math.max(maxLen + 2, 8), 50) };
  });

  // ── 5. 生成并下载 ──
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, '明细');

  const filename = sanitizeFilename(`${code}_${name}_${unitName || unit}_${startStr}_${endStr}`) + '.xlsx';
  XLSX.writeFile(wb, filename);

  return { rows: allRows.length, filename };
}
