/** 
 * screenshot-bim-color-isolate.mjs — v3.13.0 W6.6.
 *
 * Sanity-check pass for the ColorByPropertyPanel + context-menu Isolate/
 * Show-all surfaces.  Logs in, opens the first BIM model, and captures
 * three artefacts:
 *
 *   1. qa-tests/_w66-color-isolate/color-by-category.png
 *      — viewer after picking property "category" + palette "categorical-12"
 *        and clicking Apply.
 *   2. qa-tests/_w66-color-isolate/isolated.png
 *      — viewer after right-clicking an element and choosing "Isolate".
 *   3. qa-tests/_w66-color-isolate/restored.png
 *      — viewer after the "Show all" badge is clicked / Show-all action fires.
 *
 * If the ColorByPropertyPanel is not yet mounted in BIMRightPanelTabs.tsx
 * (integrator follow-up), the Color-By step is skipped with a log message
 * and the script still captures the Isolate / Show-all flow.
 */

import { chromium } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

const OUT_DIR = 'qa-tests/_w66-color-isolate';

async function main() {
  await mkdir(OUT_DIR, { recursive: true });

  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await ctx.newPage();

  // ── Login ─────────────────────────────────────────────────────────────
  await page.goto('http://localhost:5180/login', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  const demoBtn = page.getByText('Admin', { exact: false }).first();
  if (await demoBtn.count()) {
    await demoBtn.click().catch(() => {});
    await page.waitForTimeout(500);
  }
  const signInBtn = page.getByRole('button', { name: /sign in/i });
  if (await signInBtn.count()) {
    await signInBtn.first().click().catch(() => {});
    await page.waitForTimeout(2000);
  }

  // ── Navigate to first BIM model ───────────────────────────────────────
  await page.goto('http://localhost:5180/bim', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);

  // Dismiss any tour modal.
  await page.keyboard.press('Escape').catch(() => {});
  await page.waitForTimeout(200);

  // Click the first model card link.
  const firstModel = page.locator('a[href*="/bim/"]').first();
  if (await firstModel.count()) {
    await firstModel.click().catch(() => {});
  } else {
    console.log('No BIM models available — capturing the dashboard instead.');
  }
  await page.waitForTimeout(2500);

  // ── Step 1: Color by category ─────────────────────────────────────────
  const colorPanel = page.locator('[data-testid="bim-color-by-property-panel"]');
  if (await colorPanel.count()) {
    const propSelect = page.locator('[data-testid="bim-color-by-property-key"]');
    // Best-effort: pick "category" or fall back to the first option.
    const options = await propSelect.locator('option').allTextContents();
    const wanted = options.find((o) => o.toLowerCase().includes('category'))
      ?? options.find((o) => o.toLowerCase().includes('element_type'))
      ?? options[0];
    if (wanted) {
      await propSelect.selectOption({ label: wanted }).catch(() => {});
    }
    await page
      .locator('[data-testid="bim-color-by-property-palette"]')
      .selectOption('categorical-12')
      .catch(() => {});
    await page
      .locator('[data-testid="bim-color-by-property-apply"]')
      .click()
      .catch(() => {});
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT_DIR}/color-by-category.png`, fullPage: false });
    console.log('OK color-by-category captured');
  } else {
    console.log(
      'Panel not yet wired into BIMRightPanelTabs.tsx — integrator follow-up. Skipping Color-By steps.',
    );
  }

  // ── Step 2: Right-click → Isolate ─────────────────────────────────────
  // The viewer canvas is a <canvas>; right-click near the centre to spawn
  // the context menu over an element.
  const canvas = page.locator('canvas').first();
  if (await canvas.count()) {
    const bbox = await canvas.boundingBox();
    if (bbox) {
      await page.mouse.move(bbox.x + bbox.width / 2, bbox.y + bbox.height / 2);
      await page.waitForTimeout(150);
      await page.mouse.click(bbox.x + bbox.width / 2, bbox.y + bbox.height / 2, { button: 'right' });
      await page.waitForTimeout(400);
      const isolateBtn = page.locator('[data-testid="bim-ctx-isolate"]');
      if (await isolateBtn.count()) {
        await isolateBtn.first().click().catch(() => {});
        await page.waitForTimeout(800);
        await page.screenshot({ path: `${OUT_DIR}/isolated.png`, fullPage: false });
        console.log('OK isolated captured');
      } else {
        console.log('Context menu Isolate item not found — skipping.');
      }
    }
  }

  // ── Step 3: Show all ──────────────────────────────────────────────────
  // The W6.6 integrator badge (TODO) is not yet wired, so we drive Show-all
  // via the context-menu fallback.  Right-click anywhere on the canvas.
  if (await canvas.count()) {
    const bbox = await canvas.boundingBox();
    if (bbox) {
      await page.mouse.click(bbox.x + bbox.width / 2, bbox.y + bbox.height / 2, { button: 'right' });
      await page.waitForTimeout(400);
      const showAllBtn = page.locator('[data-testid="bim-ctx-show-all"]');
      if (await showAllBtn.count()) {
        await showAllBtn.first().click().catch(() => {});
        await page.waitForTimeout(800);
      } else {
        // Fallback: use the global window helper if BIMViewer exposes one.
        await page.evaluate(() => {
          const w = window;
          // @ts-ignore — integrator may expose this helper later.
          if (w.__oeBim?.showAll) w.__oeBim.showAll();
        });
        await page.waitForTimeout(400);
      }
      await page.screenshot({ path: `${OUT_DIR}/restored.png`, fullPage: false });
      console.log('OK restored captured');
    }
  }

  await browser.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
