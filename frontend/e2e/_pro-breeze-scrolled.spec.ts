import { test } from '@playwright/test';

test('scrolled state', async ({ page }) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('http://localhost:8765/pro/breeze/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(4500);
  await page.evaluate(() => {
    document.querySelectorAll('.reveal').forEach((el) => el.classList.add('is-visible'));
  });
  // Scroll to Numbers section to capture progress, floater, pager
  await page.evaluate(() => {
    document.getElementById('numbers')?.scrollIntoView({ behavior: 'instant', block: 'start' });
  });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: '../website-marketing/pro/.preview/scrolled.png', fullPage: false });
});
