import { test, expect } from '@playwright/test';

const BASE = process.env.QA_BASE_URL || 'http://localhost:5173';
const EMAIL = process.env.QA_DEMO_EMAIL || 'demo@openestimator.io';
const PASSWORD = process.env.QA_DEMO_PASSWORD || 'DemoPass1234!';

test.setTimeout(120_000);

test('geo deep diag', async ({ page }) => {
  const errors: string[] = [];
  const pageErrors: string[] = [];
  const allNetwork: Array<{ method: string; url: string; status: number | string }> = [];
  const failed: string[] = [];

  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', (err) => pageErrors.push(`${err.name}: ${err.message}`));
  page.on('requestfailed', (req) => failed.push(`${req.method()} ${req.url()} :: ${req.failure()?.errorText}`));
  page.on('response', (resp) => {
    const url = resp.url();
    // Skip Vite client / FastRefresh chatter
    if (/@vite|@react-refresh|\.css|hot-update/.test(url)) return;
    // Capture geo-hub / cesium / chunk-y stuff + all errors
    if (/geo-hub|cesium|Cesium|\.wasm|Workers|Assets|Widgets|ThirdParty|\.tsx\?|\.ts\?/.test(url) || resp.status() >= 400) {
      allNetwork.push({ method: resp.request().method(), url, status: resp.status() });
    }
  });

  // 1) Login
  await page.goto(`${BASE}/login`);
  await page.locator('input[type=email], input[name=email]').first().fill(EMAIL);
  await page.locator('input[type=password], input[name=password]').first().fill(PASSWORD);
  await page.locator('button[type=submit]').first().click();
  await page.waitForURL(/\/(dashboard|projects|geo|$)/, { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(2000);

  // 2) Navigate to /geo
  await page.goto(`${BASE}/geo`);

  // Sleep 12s and screenshot every 3s to see what loading state shows
  for (let i = 0; i < 6; i++) {
    await page.waitForTimeout(3000);
    await page.screenshot({ path: `qa-report/geo-tick-${i}.png`, fullPage: true });
  }
  const cesiumReady = (await page.locator('text=/Loading Cesium/i').count()) === 0;

  // 3) Hunt for canvas
  const canvas = page.locator('canvas');
  const canvasCount = await canvas.count();
  let canvasVisible = false;
  if (canvasCount > 0) canvasVisible = await canvas.first().isVisible().catch(() => false);

  console.log('\n=========== GEO DEEP DIAG ===========');
  console.log('Cesium ready (no Loading text):', cesiumReady);
  console.log('Canvas count:', canvasCount, 'visible:', canvasVisible);
  console.log('Page URL:', page.url());
  console.log('\n--- Cesium-related network ---');
  allNetwork.forEach((n) => console.log(`  [${n.status}] ${n.method} ${n.url}`));
  console.log('\n--- failed requests ---');
  failed.forEach((f) => console.log('  ' + f));
  console.log('\n--- console.error ---');
  errors.slice(0, 30).forEach((e) => console.log('  ' + e.slice(0, 300)));
  console.log('\n--- pageerror ---');
  pageErrors.forEach((e) => console.log('  ' + e));

  expect(true).toBeTruthy();
});
