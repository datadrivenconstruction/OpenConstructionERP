import { test } from '@playwright/test';

test('breeze check', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push('CONSOLE: ' + m.text());
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('http://localhost:8765/pro/breeze/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(5000);
  // Force final GSAP state for hero
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
  await page.screenshot({
    path: '../website-marketing/pro/.preview/breeze.png',
    fullPage: false,
  });

  // Force reveal state + counter finals for full-page screenshot
  await page.evaluate(() => {
    document.querySelectorAll('.reveal').forEach((el) => el.classList.add('is-visible'));
    document.querySelectorAll('[data-count]').forEach((el: any) => {
      const target = parseFloat(el.dataset.count || '0');
      const suffix = el.dataset.suffix || '';
      el.innerHTML = (target >= 1000 ? target.toLocaleString('en-US') : target.toString())
        + (suffix ? '<span class="suffix">' + suffix + '</span>' : '');
    });
  });
  await page.waitForTimeout(800);

  // Full page shot for review
  await page.screenshot({
    path: '../website-marketing/pro/.preview/breeze-full.png',
    fullPage: true,
  });

  if (errors.length) console.log('ERRORS:', JSON.stringify(errors));
});
