import { test } from '@playwright/test';

test.use({ reducedMotion: 'no-preference' });

test('module tiles screenshot', async ({ page }) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('http://localhost:8765/pro/breeze/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(4500);
  await page.evaluate(() => {
    document.querySelectorAll('.reveal').forEach((el) => el.classList.add('is-visible'));
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
  await page.screenshot({ path: '../website-marketing/pro/.preview/module-tiles.png', fullPage: false });
});
