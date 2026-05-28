import { test, expect } from '@playwright/test';

const BASE = process.env.QA_BASE_URL || 'http://localhost:5173';
const EMAIL = process.env.QA_DEMO_EMAIL || 'demo@openestimator.io';
const PASSWORD = process.env.QA_DEMO_PASSWORD || 'DemoPass1234!';

test.setTimeout(120_000);

test('geo DOM/CSS inspect', async ({ page }) => {
  await page.goto(`${BASE}/login`);
  await page.locator('input[type=email]').first().fill(EMAIL);
  await page.locator('input[type=password]').first().fill(PASSWORD);
  await page.locator('button[type=submit]').first().click();
  await page.waitForURL(/\/(dashboard|projects|geo|$)/, { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(2500);

  await page.goto(`${BASE}/geo`);
  await page.waitForSelector('canvas', { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(8000); // let Cesium fully mount

  const sizes = await page.evaluate(() => {
    const out: Array<{ tag: string; cls: string; w: number; h: number; rect: { w: number; h: number }; computedHeight: string; computedDisplay: string }> = [];
    // Walk up from canvas to body
    const canvas = document.querySelector('canvas');
    if (!canvas) return { error: 'no canvas', out };
    let el: HTMLElement | null = canvas as HTMLElement;
    for (let i = 0; i < 20 && el; i++) {
      const cs = window.getComputedStyle(el);
      const r = el.getBoundingClientRect();
      out.push({
        tag: el.tagName,
        cls: (el.className && typeof el.className === 'string') ? el.className.slice(0, 100) : '',
        w: el.offsetWidth,
        h: el.offsetHeight,
        rect: { w: Math.round(r.width), h: Math.round(r.height) },
        computedHeight: cs.height,
        computedDisplay: cs.display,
      });
      el = el.parentElement;
    }
    return { out, headerVar: getComputedStyle(document.documentElement).getPropertyValue('--oe-header-height'), innerHeight: window.innerHeight };
  });

  console.log('\n========== GEO DOM CHAIN ==========');
  console.log('innerHeight:', sizes.innerHeight);
  console.log('--oe-header-height:', sizes.headerVar);
  console.log('Walk from canvas up:');
  sizes.out?.forEach((row, i) => {
    console.log(`  [${i}] <${row.tag}> offset=${row.w}x${row.h} rect=${row.rect.w}x${row.rect.h} height=${row.computedHeight} display=${row.computedDisplay}`);
    console.log(`       class="${row.cls}"`);
  });
  await page.screenshot({ path: 'qa-report/geo-dom-snap.png', fullPage: true });
  expect(true).toBeTruthy();
});
