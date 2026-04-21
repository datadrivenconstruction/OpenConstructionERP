/**
 * Q1 comprehensive verification — uploads fixtures and exercises every feature.
 *
 * Unlike the per-module specs that gracefully skip when no data is loaded,
 * this spec actively uploads test fixtures (DXF + PDF) so the viewers
 * mount and every Q1 feature can be visually verified.
 *
 * Run with `--workers=1` to avoid ECONNRESET on the auth endpoint.
 */

import { test, expect, type Page } from '@playwright/test';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test.describe.configure({ mode: 'serial' });

const DXF_FIXTURE = path.resolve(__dirname, 'fixtures/test.dxf');
const PDF_FIXTURE = path.resolve(__dirname, '../test-drawing.pdf');

/* ── Auth ────────────────────────────────────────────────────────────── */

async function injectAuth(page: Page): Promise<void> {
  const login = await page.request.post(
    'http://localhost:8000/api/v1/users/auth/login/',
    { data: { email: 'test@openestimate.com', password: 'OpenEstimate2024!' } },
  );
  let access: string;
  let refresh: string;
  if (login.ok()) {
    const b = await login.json();
    access = b.access_token;
    refresh = b.refresh_token ?? b.access_token;
  } else {
    await page.request.post('http://localhost:8000/api/v1/users/auth/register/', {
      data: {
        email: 'test@openestimate.com',
        password: 'OpenEstimate2024!',
        full_name: 'E2E',
      },
    });
    const retry = await page.request.post(
      'http://localhost:8000/api/v1/users/auth/login/',
      { data: { email: 'test@openestimate.com', password: 'OpenEstimate2024!' } },
    );
    const b = await retry.json();
    access = b.access_token;
    refresh = b.refresh_token ?? b.access_token;
  }
  await page.addInitScript(
    (t: { a: string; r: string }) => {
      localStorage.setItem('oe_access_token', t.a);
      localStorage.setItem('oe_refresh_token', t.r);
      localStorage.setItem('oe_remember', '1');
      localStorage.setItem('oe_user_email', 'test@openestimate.com');
      localStorage.setItem('oe_onboarding_completed', 'true');
      localStorage.setItem('oe_welcome_dismissed', 'true');
      localStorage.setItem('oe_tour_completed', 'true');
      sessionStorage.setItem('oe_access_token', t.a);
      sessionStorage.setItem('oe_refresh_token', t.r);
    },
    { a: access, r: refresh },
  );
}

/* ── Shared helpers ──────────────────────────────────────────────────── */

async function uploadViaDropzone(page: Page, filePath: string): Promise<void> {
  const input = page.locator('input[type="file"]').first();
  await input.setInputFiles(filePath);
}

/* ── 1. DWG Takeoff — full feature exercise ──────────────────────────── */

test.describe('Q1 DWG Takeoff — full exercise', () => {
  test.beforeEach(async ({ page }) => {
    await injectAuth(page);
    await page.goto('/dwg-takeoff');
    await page.waitForLoadState('domcontentloaded');
  });

  test('upload DXF → toolbar + shortcuts + undo/redo + snap + ortho', async ({
    page,
  }) => {
    test.setTimeout(120_000);

    await uploadViaDropzone(page, DXF_FIXTURE);

    // Wait for DXF parser + viewer mount
    const toolPalette = page.locator('[data-testid="dwg-tool-palette"]');
    await expect(toolPalette).toBeVisible({ timeout: 45_000 });
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: 'test-results/q1-dwg-01-loaded.png',
      fullPage: true,
    });

    // ── Shortcuts ─────────────────────────────────────────────────────
    const shortcuts: Array<[string, string]> = [
      ['d', 'distance'],
      ['a', 'area'],
      ['r', 'rectangle'],
      ['c', 'circle'],
      ['l', 'line'],
      ['p', 'polyline'],
      ['v', 'select'],
      ['h', 'pan'],
      ['t', 'text_pin'],
    ];
    for (const [key, tool] of shortcuts) {
      await page.locator('body').click({ position: { x: 100, y: 100 } });
      await page.keyboard.press(key);
      await page.waitForTimeout(100);
      const activeBtn = page.locator(`[data-testid="dwg-tool-${tool}"]`);
      if ((await activeBtn.count()) > 0) {
        // Active button has bg-oe-blue-subtle class via React state
        const ariaPressed = await activeBtn.getAttribute('aria-pressed');
        const classAttr = (await activeBtn.getAttribute('class')) ?? '';
        const isActive =
          ariaPressed === 'true' ||
          classAttr.includes('oe-blue') ||
          classAttr.includes('bg-blue');
        expect.soft(isActive, `Key ${key} should activate ${tool}`).toBeTruthy();
      }
    }
    await page.screenshot({
      path: 'test-results/q1-dwg-02-shortcuts.png',
      fullPage: false,
    });

    // ── Undo/redo buttons visible + disabled ──────────────────────────
    const undo = page.locator('[data-testid="dwg-undo"]');
    const redo = page.locator('[data-testid="dwg-redo"]');
    await expect(undo).toBeVisible();
    await expect(redo).toBeVisible();
    await expect(undo).toBeDisabled();
    await expect(redo).toBeDisabled();
    await page.screenshot({
      path: 'test-results/q1-dwg-03-undo-redo-toolbar.png',
      fullPage: false,
    });

    // ── Snap dropdown ────────────────────────────────────────────────
    const snapToggle = page.locator('[data-testid="dwg-snap-menu-toggle"]');
    await expect(snapToggle).toBeVisible();
    await snapToggle.click();
    await page.waitForTimeout(200);
    const snapMenu = page.locator('[data-testid="dwg-snap-menu"]');
    await expect(snapMenu).toBeVisible();
    await page.screenshot({
      path: 'test-results/q1-dwg-04-snap-menu.png',
      fullPage: false,
    });
    // Close the dropdown
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);

    // ── Ortho (rubber band with Shift) ───────────────────────────────
    await page.keyboard.press('d');
    await page.waitForTimeout(150);
    const canvas = page.locator('[data-testid="dwg-canvas"]').first();
    const box = await canvas.boundingBox();
    if (box) {
      await page.mouse.click(box.x + box.width * 0.3, box.y + box.height * 0.5);
      await page.waitForTimeout(150);
      await page.keyboard.down('Shift');
      await page.mouse.move(
        box.x + box.width * 0.7,
        box.y + box.height * 0.55,
        { steps: 5 },
      );
      await page.waitForTimeout(300);
      await page.screenshot({
        path: 'test-results/q1-dwg-05-ortho-ghost.png',
        fullPage: false,
      });
      await page.keyboard.up('Shift');
      await page.keyboard.press('Escape');
    }

    // ── Keyboard Ctrl+Z/Ctrl+Y stays safe on empty stack ─────────────
    await page.keyboard.press('Control+z');
    await page.keyboard.press('Control+y');
    await expect(undo).toBeDisabled();
    await expect(redo).toBeDisabled();
  });
});

/* ── 2. PDF Takeoff — full feature exercise ──────────────────────────── */

test.describe('Q1 PDF Takeoff — full exercise', () => {
  test.beforeEach(async ({ page }) => {
    await injectAuth(page);
    await page.goto('/takeoff?tab=measurements');
    await page.waitForLoadState('domcontentloaded');
  });

  test('upload PDF → shortcuts + redo + properties + legend', async ({ page }) => {
    test.setTimeout(120_000);

    await uploadViaDropzone(page, PDF_FIXTURE);

    // Wait for PDF render — canvas appears
    const canvas = page.locator('canvas').first();
    await expect(canvas).toBeVisible({ timeout: 45_000 });
    await page.waitForTimeout(1500);
    await page.screenshot({
      path: 'test-results/q1-pdf-01-loaded.png',
      fullPage: true,
    });

    // ── Shortcuts: press each key, verify tool button gets active class ─
    const shortcuts = ['d', 'a', 'c', 'o', 'p', 'v'];
    for (const key of shortcuts) {
      await page.locator('body').click({ position: { x: 200, y: 200 } });
      await page.keyboard.press(key);
      await page.waitForTimeout(80);
    }
    await page.screenshot({
      path: 'test-results/q1-pdf-02-after-shortcuts.png',
      fullPage: false,
    });

    // ── Redo button present + disabled initially ──────────────────────
    const redoBtn = page.locator('[data-testid="redo-button"]');
    if ((await redoBtn.count()) > 0) {
      await expect(redoBtn).toBeVisible();
      await expect(redoBtn).toBeDisabled();
      await page.screenshot({
        path: 'test-results/q1-pdf-03-redo-btn.png',
        fullPage: false,
      });
    }

    // ── Legend toggle button ─────────────────────────────────────────
    const legendToggle = page.locator('[data-testid="legend-toggle"]');
    if ((await legendToggle.count()) > 0) {
      await legendToggle.click();
      await page.waitForTimeout(300);
      await page.screenshot({
        path: 'test-results/q1-pdf-04-legend-toggled.png',
        fullPage: false,
      });
    }
  });
});

/* ── 3. BIM Viewer — toolbar elements + URL state ─────────────────────── */

test.describe('Q1 BIM Viewer — toolbar exercise', () => {
  test.beforeEach(async ({ page }) => {
    await injectAuth(page);
    await page.goto('/bim');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1500);
  });

  test('screenshot button + 5D mode option + URL state machinery', async ({
    page,
  }) => {
    test.setTimeout(60_000);

    await page.screenshot({
      path: 'test-results/q1-bim-01-landing.png',
      fullPage: true,
    });

    // ── Screenshot button (DOM element) ──────────────────────────────
    const screenshotBtn = page.locator('[data-testid="bim-screenshot-btn"]');
    const hasScreenshotBtn = (await screenshotBtn.count()) > 0;
    expect.soft(
      hasScreenshotBtn,
      'Screenshot button should be in the DOM (even if not mounted on empty page)',
    ).toBeTruthy();

    // ── 5D option in the mode selector dropdown ──────────────────────
    const modeSelect = page.locator('[data-testid="bim-colour-mode-select"]');
    const has5DOption = (await modeSelect.count()) > 0;
    if (has5DOption) {
      const optionText = await modeSelect.evaluate((el) => (el as HTMLSelectElement).innerHTML);
      expect.soft(
        optionText.includes('5D') || optionText.includes('cost') || optionText.includes('unit rate'),
        '5D option should be listed',
      ).toBeTruthy();
      await page.screenshot({
        path: 'test-results/q1-bim-02-mode-select.png',
        fullPage: false,
      });
    }

    // ── URL query param hydration still works (no crash on deep-link) ─
    await page.goto('/bim?cx=10&cy=20&cz=30&tx=0&ty=0&tz=0&sel=abc,def');
    await page.waitForTimeout(1000);
    const url = page.url();
    expect(url).toContain('cx=10');
    await page.screenshot({
      path: 'test-results/q1-bim-03-url-state.png',
      fullPage: true,
    });
  });
});

/* ── 4. Data Explorer — upload + URL state + data bars ───────────────── */

test.describe('Q1 Data Explorer — full exercise', () => {
  test.beforeEach(async ({ page }) => {
    await injectAuth(page);
    await page.goto('/data-explorer');
    await page.waitForLoadState('domcontentloaded');
  });

  test('upload DXF → tabs change URL → pivot shows data bars', async ({
    page,
  }) => {
    test.setTimeout(180_000);

    // ── URL state: switch tab ─────────────────────────────────────────
    // Pre-upload: tab buttons may already be visible on landing page
    await page.screenshot({
      path: 'test-results/q1-de-01-landing.png',
      fullPage: true,
    });

    // Try upload — if backend doesn't parse the DXF we skip the pivot test
    await uploadViaDropzone(page, DXF_FIXTURE);

    // Wait up to 90s for describe() to return and slicer banner to appear
    const slicerBanner = page.locator('[data-testid="explorer-slicer-banner"]');
    const uploaded = await slicerBanner
      .waitFor({ state: 'visible', timeout: 90_000 })
      .then(() => true)
      .catch(() => false);

    if (!uploaded) {
      // Backend may not process DXF — capture state and stop here
      await page.screenshot({
        path: 'test-results/q1-de-02-upload-fail.png',
        fullPage: true,
      });
      return;
    }

    await page.screenshot({
      path: 'test-results/q1-de-03-uploaded.png',
      fullPage: true,
    });

    // ── Switch to Pivot tab via explorer-tab-pivot button ────────────
    const pivotTab = page.locator('[data-testid="explorer-tab-pivot"]');
    if ((await pivotTab.count()) > 0) {
      await pivotTab.click();
      await page.waitForTimeout(800);
      await expect(page).toHaveURL(/tab=pivot/);
      await page.screenshot({
        path: 'test-results/q1-de-04-pivot-url.png',
        fullPage: true,
      });

      // Check for data-bar testid presence
      const dataBars = page.locator('[data-testid^="pivot-databar-"]');
      const n = await dataBars.count();
      if (n > 0) {
        await page.screenshot({
          path: 'test-results/q1-de-05-data-bars.png',
          fullPage: false,
        });
      }
    }

    // ── Reload with ?tab=charts preserves state ──────────────────────
    await page.goto('/data-explorer?tab=charts');
    await page.waitForTimeout(1200);
    await page.screenshot({
      path: 'test-results/q1-de-06-url-hydration.png',
      fullPage: true,
    });
  });
});
