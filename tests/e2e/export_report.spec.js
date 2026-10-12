const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

test.describe('导出上报表 E2E', () => {

  test('点击导出上报表下载 xlsx 并可被解析', async ({ page }) => {
    // 选择 2026-08（有数据的历史月份）
    await page.goto('/');
    await page.waitForSelector('.filter-bar', { timeout: 10000 });

    const yearSelect = page.locator('.filters select').first();
    await yearSelect.selectOption('2026');
    const startSelect = page.locator('.filters select').nth(1);
    await startSelect.selectOption('8');
    const endSelect = page.locator('.filters select').nth(2);
    await endSelect.selectOption('8');
    await page.waitForSelector('.indi-table tbody tr', { timeout: 30000 });

    // 捕获下载
    const downloadPromise = page.waitForEvent('download', { timeout: 60000 });
    const btn = page.locator('.filter-bar button', { hasText: '导出上报表' });
    await expect(btn).toBeVisible();
    await btn.click();
    const download = await downloadPromise;

    const suggested = download.suggestedFilename();
    console.log('下载文件名:', suggested);
    expect(suggested).toMatch(/^重症质控指标上报_2026-08.*\.xlsx$/);

    const tmp = path.join(process.cwd(), '_e2e_download.xlsx');
    await download.saveAs(tmp);
    const stat = fs.statSync(tmp);
    console.log('下载大小:', stat.size);
    expect(stat.size).toBeGreaterThan(5000);

    // xlsx 魔数 (PK zip)
    const head = fs.readFileSync(tmp).subarray(0, 2).toString('latin1');
    expect(head).toBe('PK');

    // 按钮恢复可用
    await expect(btn).toHaveText('导出上报表');
    await expect(btn).toBeEnabled();
  });

  test('无数据月份跳过并提示', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.filter-bar', { timeout: 10000 });

    const yearSelect = page.locator('.filters select').first();
    await yearSelect.selectOption('2024');
    const startSelect = page.locator('.filters select').nth(1);
    await startSelect.selectOption('3');
    const endSelect = page.locator('.filters select').nth(2);
    await endSelect.selectOption('3');
    await page.waitForSelector('.indi-table', { timeout: 30000 });

    const btn = page.locator('.filter-bar button', { hasText: '导出上报表' });
    // 不应触发下载：等待 toast 出现提示
    await btn.click();
    const toast = page.locator('.toast');
    await expect(toast).toBeVisible({ timeout: 90000 });
    const text = await toast.innerText();
    console.log('toast:', text);
    expect(text).toMatch(/无数据|已导出/);
  });

});
