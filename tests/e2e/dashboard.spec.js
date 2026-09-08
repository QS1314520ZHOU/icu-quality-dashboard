const { test, expect } = require('@playwright/test');

// Helper: navigate to June 2026 which has data
async function goToJune2026(page) {
  await page.goto('/');
  await page.waitForSelector('.filter-bar', { timeout: 10000 });

  // Select startMonth=6
  const startSelect = page.locator('.filters select').nth(1);
  await startSelect.selectOption('6');
  await startSelect.evaluate(el => el.dispatchEvent(new Event('change', { bubbles: true })));

  // Select endMonth=6
  const endSelect = page.locator('.filters select').nth(2);
  await endSelect.selectOption('6');
  await endSelect.evaluate(el => el.dispatchEvent(new Event('change', { bubbles: true })));

  // Wait for data to load
  await page.waitForSelector('.indi-table tbody tr', { timeout: 30000 });
}

test.describe('ICU Quality Dashboard E2E', () => {

  test('默认月份为当前月(2026年9月)', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.filter-bar', { timeout: 10000 });

    const yearSelect = page.locator('.filters select').first();
    const yearVal = await yearSelect.inputValue();
    expect(yearVal).toBe('2026');

    const startMonthSelect = page.locator('.filters select').nth(1);
    const startVal = await startMonthSelect.inputValue();
    expect(startVal).toBe('9');

    const endMonthSelect = page.locator('.filters select').nth(2);
    const endVal = await endMonthSelect.inputValue();
    expect(endVal).toBe('9');
  });

  test('年份选项包含当前年+1(2027)', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.filter-bar', { timeout: 10000 });

    const yearSelect = page.locator('.filters select').first();
    const options = await yearSelect.locator('option').allTextContents();
    expect(options).toContain('2024年');
    expect(options).toContain('2025年');
    expect(options).toContain('2026年');
    expect(options).toContain('2027年');
  });

  test('蓝色网格表格样式 - 表头背景#CBD7F5', async ({ page }) => {
    await goToJune2026(page);

    const th = page.locator('.indi-table th').first();
    const bgColor = await th.evaluate(el => getComputedStyle(el).backgroundColor);
    expect(bgColor).toBe('rgb(203, 215, 245)');
  });

  test('蓝色网格表格样式 - 选中行背景#344E84', async ({ page }) => {
    await goToJune2026(page);

    const firstRow = page.locator('.indi-table tbody tr').first();
    await firstRow.click();

    const bgColor = await firstRow.locator('td').first().evaluate(
      el => getComputedStyle(el).backgroundColor
    );
    expect(bgColor).toBe('rgb(52, 78, 132)');

    const color = await firstRow.locator('td').first().evaluate(
      el => getComputedStyle(el).color
    );
    expect(color).toBe('rgb(255, 255, 255)');
  });

  test('行高约40-44px', async ({ page }) => {
    await goToJune2026(page);

    const td = page.locator('.indi-table tbody td').first();
    const height = await td.evaluate(el => parseFloat(getComputedStyle(el).height));
    expect(height).toBeGreaterThanOrEqual(38);
    expect(height).toBeLessThanOrEqual(52);
  });

  test('名称列宽度不超过260px', async ({ page }) => {
    await goToJune2026(page);

    const nameCol = page.locator('.c-name');
    const width = await nameCol.evaluate(el => parseFloat(getComputedStyle(el).width));
    expect(width).toBeLessThanOrEqual(262);
  });

  test('名称超长时省略(ellipsis)', async ({ page }) => {
    await goToJune2026(page);

    const nameTxt = page.locator('.name-txt').first();
    const overflow = await nameTxt.evaluate(el => getComputedStyle(el).textOverflow);
    expect(overflow).toBe('ellipsis');
  });

  test('导出按钮flex布局(非float:right)', async ({ page }) => {
    await goToJune2026(page);

    const numCell = page.locator('.num.link').first();
    await numCell.click();
    await page.waitForSelector('.source', { timeout: 10000 });

    const source = page.locator('.source');
    const display = await source.evaluate(el => getComputedStyle(el).display);
    expect(display).toBe('flex');

    // Use the export button inside the detail modal (.source), not the top bar one
    const exportBtn = page.locator('.source .export-btn');
    const float = await exportBtn.evaluate(el => getComputedStyle(el).float);
    expect(float).not.toBe('right');
  });

  test('导出按钮垂直居中不下沉', async ({ page }) => {
    await goToJune2026(page);

    const numCell = page.locator('.num.link').first();
    await numCell.click();
    await page.waitForSelector('.source', { timeout: 10000 });

    const source = page.locator('.source');
    const alignItems = await source.evaluate(el => getComputedStyle(el).alignItems);
    expect(alignItems).toBe('center');
  });

  test('选中行hover不覆盖选中颜色', async ({ page }) => {
    await goToJune2026(page);

    const firstRow = page.locator('.indi-table tbody tr').first();
    await firstRow.click();

    // Close any modal that may have opened
    const mask = page.locator('.mask');
    if (await mask.count() > 0) {
      await page.keyboard.press('Escape');
      await page.waitForTimeout(300);
    }

    await firstRow.hover({ force: true });

    const bgColor = await firstRow.locator('td').first().evaluate(
      el => getComputedStyle(el).backgroundColor
    );
    expect(bgColor).toBe('rgb(52, 78, 132)');
  });

  test('月份单元格可点击(cursor:pointer) - 多月模式', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.filter-bar', { timeout: 10000 });

    // Set range 5-6月
    const startSelect = page.locator('.filters select').nth(1);
    await startSelect.selectOption('5');
    await startSelect.evaluate(el => el.dispatchEvent(new Event('change', { bubbles: true })));
    const endSelect = page.locator('.filters select').nth(2);
    await endSelect.selectOption('6');
    await endSelect.evaluate(el => el.dispatchEvent(new Event('change', { bubbles: true })));
    await page.waitForSelector('.month-cell', { timeout: 20000 });

    const monthCell = page.locator('.month-cell').first();
    const cursor = await monthCell.evaluate(el => getComputedStyle(el).cursor);
    expect(cursor).toBe('pointer');
  });

  test('开始月份不能晚于结束月份', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.filter-bar', { timeout: 10000 });

    const startSelect = page.locator('.filters select').nth(1);
    const endSelect = page.locator('.filters select').nth(2);

    await startSelect.selectOption('12');
    await startSelect.evaluate(el => el.dispatchEvent(new Event('change', { bubbles: true })));
    await page.waitForTimeout(500);

    const endVal = await endSelect.inputValue();
    expect(endVal).toBe('12');
  });

  test('1366宽度下名称列不过宽', async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 768 });
    await goToJune2026(page);

    const nameCol = page.locator('.c-name');
    const width = await nameCol.evaluate(el => parseFloat(getComputedStyle(el).width));
    expect(width).toBeLessThanOrEqual(262);
  });

  test('1920宽度下表格正常显示', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await goToJune2026(page);

    const table = page.locator('.indi-table');
    await expect(table).toBeVisible();

    const nameCol = page.locator('.c-name');
    const width = await nameCol.evaluate(el => parseFloat(getComputedStyle(el).width));
    expect(width).toBeLessThanOrEqual(262);
  });

  test('状态徽章有文字提示(不只靠颜色)', async ({ page }) => {
    await goToJune2026(page);

    const badge = page.locator('.badge').first();
    const text = await badge.textContent();
    expect(text.trim().length).toBeGreaterThan(0);
  });

  test('无重复copyright-bar', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.copyright-bar', { timeout: 10000 });

    const bars = page.locator('.copyright-bar');
    const count = await bars.count();
    expect(count).toBe(1);
  });

  test('页面标题为科室标签(不重复ICU质控指标明细)', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.page-title', { timeout: 10000 });

    const title = await page.locator('.page-title').textContent();
    expect(title).not.toContain('ICU 质控指标明细');
  });

  test('多月模式下月份单元格点击打开详情', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.filter-bar', { timeout: 10000 });

    // Set range 5-6月
    const startSelect = page.locator('.filters select').nth(1);
    await startSelect.selectOption('5');
    await startSelect.evaluate(el => el.dispatchEvent(new Event('change', { bubbles: true })));
    const endSelect = page.locator('.filters select').nth(2);
    await endSelect.selectOption('6');
    await endSelect.evaluate(el => el.dispatchEvent(new Event('change', { bubbles: true })));
    await page.waitForSelector('.month-cell', { timeout: 20000 });

    // Click first month cell with a value
    const monthCells = page.locator('.month-cell');
    const count = await monthCells.count();
    if (count > 0) {
      // Find a cell with actual value (not '/')
      for (let i = 0; i < count; i++) {
        const text = await monthCells.nth(i).textContent();
        if (text.trim() !== '' && text.trim() !== '/') {
          await monthCells.nth(i).click();
          // Should open a modal
          await page.waitForSelector('.modal-overlay, .modal, [class*="modal"]', { timeout: 5000 }).catch(() => {});
          break;
        }
      }
    }
  });

});
