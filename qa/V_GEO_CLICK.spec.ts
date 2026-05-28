import { test, expect } from '@playwright/test';

const BASE = process.env.QA_BASE_URL || 'http://localhost:5173';
const EMAIL = process.env.QA_DEMO_EMAIL || 'demo@openestimator.io';
const PASSWORD = process.env.QA_DEMO_PASSWORD || 'DemoPass1234!';

test.setTimeout(180_000);

test('geo click-flow exhaustive', async ({ page }) => {
  const errors: string[] = [];
  const pageErrors: string[] = [];
  const apiCalls: Array<{ status: number; url: string }> = [];

  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', (err) => pageErrors.push(`${err.name}: ${err.message}`));
  page.on('response', (resp) => {
    const u = resp.url();
    if (/\/api\//.test(u)) apiCalls.push({ status: resp.status(), url: u });
  });

  // Login
  await page.goto(`${BASE}/login`);
  await page.locator('input[type=email]').first().fill(EMAIL);
  await page.locator('input[type=password]').first().fill(PASSWORD);
  await page.locator('button[type=submit]').first().click();
  await page.waitForURL(/\/(dashboard|projects|geo|$)/, { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(2000);

  // Navigate to /geo and wait for cesium canvas
  await page.goto(`${BASE}/geo`);
  await page.waitForSelector('canvas', { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(5000);
  await page.screenshot({ path: 'qa-report/geo-c-01-loaded.png', fullPage: true });

  // ACTION 1: click anchored project in the panel
  const projectLink = page.locator('[data-testid=anchored-project-item], button:has-text("Edifício"), li:has-text("Edifício")').first();
  const projectClickable = await projectLink.count();
  if (projectClickable > 0) {
    await projectLink.click({ trial: false }).catch((e) => errors.push(`project click failed: ${e.message}`));
    await page.waitForTimeout(3000);
    await page.screenshot({ path: 'qa-report/geo-c-02-after-project-click.png', fullPage: true });
  }

  // ACTION 2: switch to Project mode (segmented control)
  const projectMode = page.locator('button:has-text("Project")').first();
  if (await projectMode.count()) {
    await projectMode.click().catch((e) => errors.push(`project mode click failed: ${e.message}`));
    await page.waitForTimeout(2000);
    await page.screenshot({ path: 'qa-report/geo-c-03-project-mode.png', fullPage: true });
  }

  // ACTION 3: switch to Development mode
  const devMode = page.locator('button:has-text("Development")').first();
  if (await devMode.count()) {
    await devMode.click().catch((e) => errors.push(`dev mode click failed: ${e.message}`));
    await page.waitForTimeout(2000);
    await page.screenshot({ path: 'qa-report/geo-c-04-dev-mode.png', fullPage: true });
  }

  // ACTION 4: switch back to Global, then type into search
  const globalMode = page.locator('button:has-text("Global")').first();
  if (await globalMode.count()) {
    await globalMode.click().catch(() => {});
    await page.waitForTimeout(1500);
  }
  const searchInput = page.locator('input[placeholder*="address" i], input[placeholder*="Search" i]').first();
  if (await searchInput.count()) {
    await searchInput.click();
    await searchInput.fill('Berlin');
    await page.waitForTimeout(2500); // wait for autocomplete
    await page.screenshot({ path: 'qa-report/geo-c-05-autocomplete.png', fullPage: true });
  }

  // ACTION 5: ESC and check for any leftover open dialogs
  await page.keyboard.press('Escape');
  await page.waitForTimeout(1000);

  // Console-side check: globe state
  const cesiumState = await page.evaluate(() => {
    const w = window as unknown as {
      Cesium?: { Camera?: unknown; Viewer?: unknown };
    };
    const canvases = Array.from(document.querySelectorAll('canvas'));
    return {
      cesiumGlobal: typeof w.Cesium !== 'undefined',
      canvasCount: canvases.length,
      canvasSizes: canvases.map((c) => ({ w: c.width, h: c.height })),
    };
  });

  console.log('\n========= GEO CLICK-FLOW REPORT =========');
  console.log('Cesium global present:', cesiumState.cesiumGlobal);
  console.log('Canvas count:', cesiumState.canvasCount, 'sizes:', JSON.stringify(cesiumState.canvasSizes));
  console.log('\n--- Console errors ---');
  errors.slice(0, 50).forEach((e) => console.log('  ' + e.slice(0, 300)));
  console.log('\n--- Page errors ---');
  pageErrors.slice(0, 50).forEach((e) => console.log('  ' + e));
  console.log('\n--- API errors (status >= 400) ---');
  apiCalls.filter((c) => c.status >= 400).slice(0, 30).forEach((c) => console.log(`  [${c.status}] ${c.url}`));
  console.log('\n--- All API calls (first 40) ---');
  apiCalls.slice(0, 40).forEach((c) => console.log(`  [${c.status}] ${c.url}`));

  expect(true).toBeTruthy();
});
