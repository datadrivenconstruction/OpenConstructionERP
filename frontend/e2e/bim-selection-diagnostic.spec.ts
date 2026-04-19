/**
 * Diagnostic E2E test for BIM 3D viewer element selection.
 * Captures full console output, network errors, and probes selection UX
 * by clicking multiple points across the canvas.
 *
 * Run: npx playwright test e2e/bim-selection-diagnostic.spec.ts --headed
 */
import { test, expect, type ConsoleMessage, type Page } from '@playwright/test';

const MODEL_ID = process.env.BIM_MODEL_ID ?? 'b2c6d3fc-1c03-4812-a138-53074f52d085';
const EMAIL = process.env.BIM_TEST_EMAIL ?? 'demo@openestimator.io';
const PASSWORD = process.env.BIM_TEST_PASSWORD ?? 'DemoPass1234!';

async function login(page: Page): Promise<void> {
  await page.goto('/login');
  await page.locator('input[type="email"]').fill(EMAIL);
  await page.locator('#login-password').fill(PASSWORD);
  await page.locator('button[type="submit"]').click();
  await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 });
}

async function collectLogs(page: Page, sink: string[]): Promise<void> {
  page.on('console', (msg: ConsoleMessage) => {
    const type = msg.type();
    sink.push(`[${type}] ${msg.text()}`);
  });
  page.on('pageerror', (err) => sink.push(`[pageerror] ${err.message}`));
  page.on('requestfailed', (req) =>
    sink.push(`[reqfail] ${req.method()} ${req.url()} — ${req.failure()?.errorText ?? ''}`),
  );
}

test.setTimeout(180_000);

test('BIM selection diagnostic — collect console + click canvas', async ({ page }) => {
  const logs: string[] = [];
  await collectLogs(page, logs);

  await login(page);

  await page.goto(`/bim/${MODEL_ID}`);

  // Wait for the WebGL canvas to appear (rendered by BIMViewer).
  const canvas = page.locator('canvas').first();
  await expect(canvas).toBeVisible({ timeout: 30_000 });

  // Wait for the loading overlay to disappear — the overlay is
  // "absolute inset-0 ... bg-surface-secondary/80" and blocks clicks while
  // geometry downloads. Once it's gone, the canvas receives pointer events.
  await expect(
    page.locator('.absolute.inset-0.bg-surface-secondary\\/80').first(),
  ).toHaveCount(0, { timeout: 90_000 });
  // Give Three.js one render cycle + camera zoom-to-fit time.
  await page.waitForTimeout(1_500);

  const canvasBox = await canvas.boundingBox();
  expect(canvasBox, 'canvas must have a bounding box').toBeTruthy();
  if (!canvasBox) return;

  console.log(`\n=== Canvas box: ${JSON.stringify(canvasBox)} ===`);

  // Click 9 points across the canvas and record whether a properties panel
  // appeared each time.
  const points = [
    [0.3, 0.3], [0.5, 0.3], [0.7, 0.3],
    [0.3, 0.5], [0.5, 0.5], [0.7, 0.5],
    [0.3, 0.7], [0.5, 0.7], [0.7, 0.7],
  ];

  const results: Array<{ x: number; y: number; panel: boolean; hoverCursor: string; topElem: string; panelText: string }> = [];

  for (const [rx, ry] of points) {
    const x = canvasBox.x + canvasBox.width * rx;
    const y = canvasBox.y + canvasBox.height * ry;

    // Probe which DOM element sits at the click point (checks for overlays).
    const topElem = await page.evaluate(([px, py]) => {
      const el = document.elementFromPoint(px as number, py as number);
      if (!el) return 'null';
      return `${el.tagName}${el.className ? '.' + String(el.className).slice(0, 80) : ''}`;
    }, [x, y]);

    await page.mouse.move(x, y);
    await page.waitForTimeout(200);
    const hoverCursor = await canvas.evaluate((el) => (el as HTMLElement).style.cursor || 'default');
    await page.mouse.click(x, y);
    await page.waitForTimeout(500);

    const panelCount = await page.locator('[data-testid="bim-properties-panel"]').count();
    const panelText = await page
      .locator('[data-testid="bim-properties-panel"]')
      .first()
      .evaluate((el) => (el as HTMLElement).innerText.replace(/\s+/g, ' ').slice(0, 200))
      .catch(() => '');

    results.push({ x: rx, y: ry, panel: panelCount > 0, hoverCursor, topElem, panelText });
  }

  console.log('\n=== Click results ===');
  for (const r of results) {
    console.log(`(${r.x.toFixed(2)}, ${r.y.toFixed(2)}) cursor=${r.hoverCursor} panel=${r.panel} top=${r.topElem}`);
    if (r.panelText) console.log(`    panelText="${r.panelText.replace(/\s+/g, ' ').slice(0, 180)}"`);
  }

  // Take a final screenshot for inspection.
  await page.screenshot({ path: 'e2e/bim-selection-final.png', fullPage: false });

  console.log('\n=== Console log tail (last 80 lines) ===');
  for (const line of logs.slice(-80)) console.log(line);

  const bimLogs = logs.filter((l) => l.includes('[BIM]') || l.includes('mesh match'));
  console.log('\n=== [BIM] logs ===');
  for (const line of bimLogs) console.log(line);

  const errors = logs.filter((l) => l.startsWith('[error]') || l.startsWith('[pageerror]') || l.startsWith('[reqfail]'));
  console.log(`\n=== Errors (${errors.length}) ===`);
  for (const line of errors) console.log(line);

  // Report — do not fail the test on selection broken, we want the output.
  const anyPanel = results.some((r) => r.panel);
  console.log(`\n=== Summary: panel appeared on at least one click: ${anyPanel} ===`);
});
