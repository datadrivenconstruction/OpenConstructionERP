import { test } from '@playwright/test';

test('module-guide modal opens and closes', async ({ page }) => {
  test.setTimeout(60000);
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('http://localhost:8765/pro/breeze/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(1500);
  await page.evaluate(() => document.querySelectorAll('.reveal').forEach((el) => el.classList.add('is-visible')));

  const community = await page.$('#community');
  if (community) await community.scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);

  await page.click('#open-module-guide');
  await page.waitForTimeout(400);

  const isOpen = await page.evaluate(() => {
    const m = document.getElementById('module-guide-modal');
    return { hidden: m?.hidden, isOpen: m?.classList.contains('is-open'), overflow: document.body.style.overflow };
  });
  console.log('AFTER OPEN:', JSON.stringify(isOpen));

  await page.screenshot({ path: '../website-marketing/pro/.preview/module-guide-modal.png', fullPage: false });

  await page.keyboard.press('Escape');
  await page.waitForTimeout(400);
  const afterClose = await page.evaluate(() => {
    const m = document.getElementById('module-guide-modal');
    return { hidden: m?.hidden, isOpen: m?.classList.contains('is-open') };
  });
  console.log('AFTER ESC:', JSON.stringify(afterClose));
  console.log('ERRORS:', errors.slice(0, 3));
});
