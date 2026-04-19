import { test } from '@playwright/test';

test('breeze production', async ({ page }) => {
  test.setTimeout(90000);
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push('CONSOLE: ' + m.text());
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('https://openconstructionerp.com/pro/breeze/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(6000);
  await page.evaluate(() => {
    document.querySelectorAll('.word > span').forEach((el: any) => {
      el.style.transform = 'translate(0,0)';
      el.style.opacity = '1';
    });
    document.querySelectorAll('#fx-eyebrow,#fx-sub,#fx-ctas,#install-wrap,#fx-meta,#hero-panel').forEach((el: any) => {
      el.style.opacity = '1';
      el.style.transform = 'none';
    });
  });
  await page.waitForTimeout(500);
  await page.screenshot({ path: '../website-marketing/pro/.preview/breeze-prod.png', fullPage: false });
  if (errors.length) console.log('ERRORS:', JSON.stringify(errors));
});
