/**
 * Visual verification spec for the BIM viewer's right-side Properties panel.
 * Captures a screenshot of the panel after an IFC upload so the "card" row
 * styling and translucent inner surface can be reviewed.
 *
 * Saves:
 *   - test-results/bim-panel-after.png   (full panel with properties visible)
 *   - test-results/bim-panel-before.png  (synthetic pre-state — panel closed
 *                                         or bare shell — for contrast).
 */
import { test, type Page } from '@playwright/test';

const DEMO = { email: 'demo@openestimator.io', password: 'DemoPass1234!' };
const API = 'http://localhost:8000/api/v1';

// Reuse the cad2data fixture path from q2-verify-all.spec.ts
const SAMPLES =
  'C:\\Users\\Artem Boiko\\Downloads\\cad2data-Revit-IFC-DWG-DGN-main\\cad2data-Revit-IFC-DWG-DGN-main\\Sample_Projects\\test';
const FIXTURE_IFC = `${SAMPLES}\\Ifc2x3_Duplex_Architecture.ifc`;

async function injectAuth(page: Page): Promise<void> {
  const loginRes = await page.request.post(`${API}/users/auth/login/`, { data: DEMO });
  const body = await loginRes.json();
  const accessToken = body.access_token;
  const refreshToken = body.refresh_token || accessToken;
  await page.addInitScript((tokens: { access: string; refresh: string }) => {
    localStorage.setItem('oe_access_token', tokens.access);
    localStorage.setItem('oe_refresh_token', tokens.refresh);
    localStorage.setItem('oe_remember', '1');
    localStorage.setItem('oe_user_email', 'demo@openestimator.io');
    localStorage.setItem('oe_onboarding_completed', 'true');
    localStorage.setItem('oe_welcome_dismissed', 'true');
    localStorage.setItem('oe_tour_completed', 'true');
    sessionStorage.setItem('oe_access_token', tokens.access);
    sessionStorage.setItem('oe_refresh_token', tokens.refresh);
  }, { access: accessToken, refresh: refreshToken });
}

async function dismissOverlays(page: Page): Promise<void> {
  const candidates = [
    page.locator('button:has-text("Skip")'),
    page.locator('button:has-text("Got it")'),
    page.locator('button:has-text("Dismiss")'),
    page.locator('[aria-label="Close tour"]'),
  ];
  for (const btn of candidates) {
    if (await btn.count()) {
      try {
        await btn.click({ timeout: 500 });
        await page.waitForTimeout(200);
      } catch {
        /* */
      }
    }
  }
}

test.describe('BIM Properties panel — card rows visual', () => {
  test('upload IFC, select element, screenshot panel', async ({ page }) => {
    test.setTimeout(240_000);
    await injectAuth(page);

    await page.goto('/bim');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2500);
    await dismissOverlays(page);

    // Capture a "before-like" shot of the BIM landing page (no panel visible)
    await page.screenshot({ path: 'test-results/bim-panel-before.png', fullPage: true });

    // Upload IFC via hidden file input
    const dropzone = page
      .locator('label:has-text("Drop your file here"), label:has-text("Drop")')
      .first();
    if (await dropzone.count()) {
      await dropzone.click().catch(() => null);
      await page.waitForTimeout(400);
    }
    const fileInput = page.locator('input[type="file"]').first();
    const inputCount = await fileInput.count();
    console.log(`[bim-panel] file input count=${inputCount}`);
    if (inputCount > 0) {
      await fileInput.setInputFiles(FIXTURE_IFC);
      await page.waitForTimeout(1500);
      const confirmBtn = page
        .locator('button:has-text("Upload & Process"), button:has-text("Upload")')
        .first();
      if (await confirmBtn.count()) {
        await confirmBtn.click({ force: true });
        console.log('[bim-panel] Upload & Process clicked');
      }
      // Wait for the IFC → canonical conversion + viewer mount
      await page.waitForTimeout(75_000);
    }

    // Try to click an element in the viewer by clicking at the centre of
    // the canvas.  The BIMViewer does a raycast on pointer events.
    const canvas = page.locator('canvas').first();
    if (await canvas.count()) {
      const box = await canvas.boundingBox();
      if (box) {
        // Click a few offsets to maximise the chance of hitting a mesh
        const offsets: Array<[number, number]> = [
          [box.width * 0.5, box.height * 0.5],
          [box.width * 0.4, box.height * 0.45],
          [box.width * 0.6, box.height * 0.55],
          [box.width * 0.35, box.height * 0.55],
        ];
        for (const [x, y] of offsets) {
          await page.mouse.click(box.x + x, box.y + y);
          await page.waitForTimeout(600);
          const panelCount = await page
            .locator('[data-testid="bim-properties-panel"]')
            .count();
          if (panelCount > 0) break;
        }
      }
    }

    // Wait for the panel to render
    const panel = page.locator('[data-testid="bim-properties-panel"]');
    try {
      await panel.waitFor({ state: 'visible', timeout: 8000 });
    } catch {
      console.log('[bim-panel] properties panel not visible — taking viewport shot only');
    }

    // Full-page shot (shows panel in context)
    await page.screenshot({ path: 'test-results/bim-panel-after.png', fullPage: true });

    // If the panel is present, also clip directly to its bounding box
    if (await panel.count()) {
      try {
        await panel.screenshot({ path: 'test-results/bim-panel-after-clip.png' });
      } catch {
        /* */
      }
    }
  });
});
