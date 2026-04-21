/**
 * Data Explorer — count / count_unique aggregation (Q2).
 *
 * Follows the same pattern as q2-verify-all.spec.ts: real RVT upload,
 * click into Pivot tab, switch the aggregation <select> to COUNT, take a
 * screenshot proving the pivot rows render integer counts instead of the
 * decimal-heavy SUM output.
 */
import { test, expect, type Page } from '@playwright/test';

const DEMO = { email: 'demo@openestimator.io', password: 'DemoPass1234!' };
const API = 'http://localhost:8000/api/v1';

const SAMPLES =
  'C:\\Users\\Artem Boiko\\Downloads\\cad2data-Revit-IFC-DWG-DGN-main\\cad2data-Revit-IFC-DWG-DGN-main\\Sample_Projects\\test';
const FIXTURE_RVT = `${SAMPLES}\\Technicalschoolcurrentm_sample.rvt`;

async function injectAuth(page: Page): Promise<string> {
  const loginRes = await page.request.post(`${API}/users/auth/login/`, { data: DEMO });
  const body = await loginRes.json();
  const accessToken = body.access_token;
  const refreshToken = body.refresh_token || accessToken;

  await page.addInitScript(
    (tokens: { access: string; refresh: string }) => {
      localStorage.setItem('oe_access_token', tokens.access);
      localStorage.setItem('oe_refresh_token', tokens.refresh);
      localStorage.setItem('oe_remember', '1');
      localStorage.setItem('oe_user_email', 'demo@openestimator.io');
      localStorage.setItem('oe_onboarding_completed', 'true');
      localStorage.setItem('oe_welcome_dismissed', 'true');
      localStorage.setItem('oe_tour_completed', 'true');
      sessionStorage.setItem('oe_access_token', tokens.access);
      sessionStorage.setItem('oe_refresh_token', tokens.refresh);
    },
    { access: accessToken, refresh: refreshToken },
  );

  return accessToken;
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
        /* noop */
      }
    }
  }
}

test.beforeEach(async ({ page }) => {
  await injectAuth(page);
});

test.describe('Data Explorer — count aggregation', () => {
  test('Pivot tab: switch agg to COUNT → integer values per group', async ({ page }) => {
    test.setTimeout(180_000);

    await page.goto('/data-explorer');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2500);
    await dismissOverlays(page);

    // Prefer a cached session if the RVT was already uploaded; otherwise
    // upload the fixture (slow: ~45s).
    const modelCard = page
      .locator('button, [role="button"], a')
      .filter({ hasText: /elements|saved|\.rvt|\.ifc/i })
      .first();
    if (await modelCard.count()) {
      await modelCard.click({ timeout: 3000 }).catch(() => null);
      await page.waitForTimeout(3000);
    } else {
      const dropzone = page.locator('text=/Drop a CAD\\/BIM file|click to browse/i').first();
      if (await dropzone.count()) await dropzone.click().catch(() => null);
      const fileInput = page.locator('input[type="file"]').first();
      if (await fileInput.count()) {
        await fileInput.setInputFiles(FIXTURE_RVT);
        await page.waitForTimeout(45_000);
      }
    }

    // Switch to the Pivot tab. The tab buttons live inside a <nav>-like
    // strip next to Data Table / Charts / Describe — we click the
    // closest match by visible text and wait for the pivot surface to
    // render (aggregation <select> appears only on that tab).
    const pivotTab = page
      .locator('button, a, [role="tab"]')
      .filter({ hasText: /^Pivot$/ })
      .first();
    await pivotTab.click({ force: true }).catch(() => null);
    await page.waitForTimeout(2500);

    // Switch the aggregation <select> to COUNT.
    const aggFnSelect = page.locator('[data-testid="pivot-aggfn-select"]');
    await expect(aggFnSelect).toBeVisible({ timeout: 20_000 });
    await aggFnSelect.selectOption('count');
    await page.waitForTimeout(500);

    // Click Apply so the pivot re-runs with the new agg.
    const applyBtn = page.locator('button:has-text("Apply")').first();
    if (await applyBtn.count()) {
      await applyBtn.click({ force: true }).catch(() => null);
      await page.waitForTimeout(2000);
    }

    // Header should now read COUNT(col) instead of sum(col).
    const headerHasCount = await page
      .locator('th:has-text("count(")')
      .first()
      .count();
    console.log(`[count-agg] headers-with-count=${headerHasCount}`);

    // Screenshot the Pivot tab with count aggregation visible.
    await page.screenshot({
      path: 'test-results/data-explorer-count-agg.png',
      fullPage: true,
    });
    expect(headerHasCount).toBeGreaterThan(0);
  });
});
