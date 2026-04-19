/**
 * Round 4 visual verification sweep — v1.9.3 quality pass.
 *
 * Captures a screenshot per route that was touched by R2/R3/R4 so the
 * reviewer can eyeball every change end-to-end without driving each UI
 * feature by hand.
 */
import { test, expect, type Page } from '@playwright/test';
import { loginV19, firstProjectId } from './helpers-v19';

async function snap(page: Page, name: string) {
  await page.waitForLoadState('domcontentloaded');
  // Let React Query + Recharts settle — most heavy pages issue 3-6 parallel
  // fetches after mount. networkidle gives each page a fair chance to render
  // real content before we capture, with a generous cap so one slow request
  // doesn't block the whole sweep.
  try {
    await page.waitForLoadState('networkidle', { timeout: 15_000 });
  } catch {
    // fall through — some pages keep polling WebSockets and never idle.
  }
  // Give loading spinners a chance to unmount. Poll for "Analyzing project…"
  // style placeholders and wait for them to disappear if present.
  const spinnerHints = [
    'text=/Analyzing project/i',
    'text=/Loading/i',
    '[data-testid="page-loading"]',
  ];
  for (const sel of spinnerHints) {
    const loc = page.locator(sel);
    try {
      if (await loc.first().isVisible({ timeout: 250 })) {
        await loc.first().waitFor({ state: 'hidden', timeout: 8_000 });
      }
    } catch {
      // spinner never appeared or never disappeared — keep going.
    }
  }
  // Final paint settle.
  await page.waitForTimeout(800);
  await page.screenshot({
    path: `test-results/v1.9/screenshots/${name}.png`,
    fullPage: true,
  });
}

test.describe('v1.9.3 — Round 4 screenshot sweep', () => {
  test('capture all v1.9-touched routes', async ({ page }) => {
    test.setTimeout(600_000);
    await loginV19(page);
    const projectId = await firstProjectId(page);

    // Dashboard — R3 #1 local DDC logo
    await page.goto('/');
    await snap(page, '01-dashboard');

    // Projects list
    await page.goto('/projects');
    await snap(page, '02-projects');

    // Project detail (if project exists)
    if (projectId) {
      await page.goto(`/projects/${projectId}`);
      await snap(page, '03-project-detail');

      // Meetings — R2 #29
      await page.goto(`/meetings?project_id=${projectId}`);
      await snap(page, '04-meetings');

      // BOQ — R1 #2
      await page.goto(`/boq?project_id=${projectId}`);
      await snap(page, '05-boq');

      // Data Explorer — R2 #16 (Recharts + slicers)
      await page.goto('/data-explorer');
      await snap(page, '06-data-explorer');

      // CDE — R2 #33 (ISO 19650)
      await page.goto(`/cde?project_id=${projectId}`);
      await snap(page, '07-cde');

      // BIM Rules — R2 #24 (Quantity Rules redesign, BETA badge)
      await page.goto('/bim/rules');
      await snap(page, '08-bim-rules');

      // DWG Takeoff — R2 #11 + R4 #10/#14/#15
      await page.goto(`/dwg-takeoff?project_id=${projectId}`);
      await snap(page, '09-dwg-takeoff');

      // Project Intelligence / Estimation Dashboard — R2 #25
      await page.goto(`/project-intelligence?project_id=${projectId}`);
      await snap(page, '10-estimation-dashboard');

      // Schedule — R3 #26
      await page.goto(`/schedule?project_id=${projectId}`);
      await snap(page, '11-schedule');

      // Submittals — R3 #30 (Edit dialog)
      await page.goto(`/submittals?project_id=${projectId}`);
      await snap(page, '12-submittals');

      // Documents — R3 #32 (filters)
      await page.goto(`/documents?project_id=${projectId}`);
      await snap(page, '13-documents');

      // Transmittals — R2 #33 (revision cross-link)
      await page.goto(`/transmittals?project_id=${projectId}`);
      await snap(page, '14-transmittals');

      // Tasks — R1 #27
      await page.goto(`/tasks?project_id=${projectId}`);
      await snap(page, '15-tasks');
    }

    // Settings
    await page.goto('/settings');
    await snap(page, '16-settings');

    // About — changelog + version
    await page.goto('/about');
    await snap(page, '17-about');

    // Header - verify no "No network" banner (R3 #3)
    await page.goto('/');
    const banner = page.locator('text=/No network connection/i');
    await expect(banner).toHaveCount(0);
  });
});
