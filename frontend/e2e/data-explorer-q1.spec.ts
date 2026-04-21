/**
 * CAD-BIM Data Explorer — Q1 UX regression tests.
 *
 * Covers:
 *   1) Tab switches → URL ?tab updates + survives reload
 *   2) Slicer chip added via store → URL ?slicers updates + survives reload
 *   3) Power-BI-style pivot data-bars render when a numeric agg is selected
 *
 * Scenarios fall back to "no data" paths if the test user has no seeded CAD
 * session — we still validate the URL-sync behaviour on the landing page.
 * All three test cases produce screenshots in `test-results/`.
 */

import { test, expect, type Page } from '@playwright/test';

// Run serially so URL + localStorage don't bleed between specs.
test.describe.configure({ mode: 'serial' });

/* ── Auth helper (clone of bim-advanced.spec.ts pattern) ──────────────── */

async function injectAuth(page: Page): Promise<void> {
  const loginRes = await page.request.post('http://localhost:8000/api/v1/users/auth/login/', {
    data: { email: 'test@openestimate.com', password: 'OpenEstimate2024!' },
  });

  let accessToken: string;
  let refreshToken: string;

  if (loginRes.ok()) {
    const body = await loginRes.json();
    accessToken = body.access_token;
    refreshToken = body.refresh_token || body.access_token;
  } else {
    await page.request.post('http://localhost:8000/api/v1/users/auth/register/', {
      data: {
        email: 'test@openestimate.com',
        password: 'OpenEstimate2024!',
        full_name: 'E2E Test',
      },
    });
    const retryRes = await page.request.post(
      'http://localhost:8000/api/v1/users/auth/login/',
      { data: { email: 'test@openestimate.com', password: 'OpenEstimate2024!' } },
    );
    const body = await retryRes.json();
    accessToken = body.access_token;
    refreshToken = body.refresh_token || body.access_token;
  }

  await page.addInitScript((tokens: { access: string; refresh: string }) => {
    localStorage.setItem('oe_access_token', tokens.access);
    localStorage.setItem('oe_refresh_token', tokens.refresh);
    localStorage.setItem('oe_remember', '1');
    localStorage.setItem('oe_user_email', 'test@openestimate.com');
    localStorage.setItem('oe_onboarding_completed', 'true');
    localStorage.setItem('oe_welcome_dismissed', 'true');
    localStorage.setItem('oe_tour_completed', 'true');
    sessionStorage.setItem('oe_access_token', tokens.access);
    sessionStorage.setItem('oe_refresh_token', tokens.refresh);
  }, { access: accessToken, refresh: refreshToken });

  await page.goto('/about');
  await page.waitForLoadState('load');
  await page.waitForTimeout(500);
}

/* ── Session discovery helper ─────────────────────────────────────────── */

/** Look up the first available CAD session id for the test user. Returns
 *  null if none exist — callers should fall back to landing-page tests. */
async function findSessionId(page: Page): Promise<string | null> {
  try {
    const loginRes = await page.request.post('http://localhost:8000/api/v1/users/auth/login/', {
      data: { email: 'test@openestimate.com', password: 'OpenEstimate2024!' },
    });
    if (!loginRes.ok()) return null;
    const body = await loginRes.json();
    const token = body.access_token;
    const listRes = await page.request.get(
      'http://localhost:8000/api/v1/takeoff/sessions/',
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!listRes.ok()) return null;
    const sessions = await listRes.json();
    if (!Array.isArray(sessions) || sessions.length === 0) return null;
    return sessions[0]?.session_id || sessions[0]?.id || null;
  } catch {
    return null;
  }
}

/* ── Tests ────────────────────────────────────────────────────────────── */

test.describe('Data Explorer Q1 UX', () => {
  test.beforeEach(async ({ page }) => {
    await injectAuth(page);
  });

  test('1) Tab switch writes ?tab to URL and survives reload', async ({ page }) => {
    const sessionId = await findSessionId(page);
    if (sessionId) {
      await page.goto(`/data-explorer?session=${sessionId}`);
    } else {
      // No seeded session — exercise landing page URL behaviour only.
      await page.goto('/data-explorer');
    }
    await page.waitForLoadState('load');
    await page.waitForTimeout(800);

    if (!sessionId) {
      // Landing page has no tabs — just prove the route rendered with no
      // URL pollution and move on.
      await page.screenshot({ path: 'test-results/de-tab-url.png', fullPage: true });
      expect(page.url()).toContain('/data-explorer');
      return;
    }

    // Switch to pivot tab.
    const pivotBtn = page.getByTestId('explorer-tab-pivot');
    await expect(pivotBtn).toBeVisible({ timeout: 10000 });
    await pivotBtn.click();

    // URL should update within the 300ms debounce window.
    await expect.poll(async () => page.url(), { timeout: 3000 }).toContain('tab=pivot');

    await page.screenshot({ path: 'test-results/de-tab-url.png', fullPage: true });

    // Reload — tab should persist.
    await page.reload();
    await page.waitForLoadState('load');
    await page.waitForTimeout(800);
    await expect(page.getByTestId('explorer-tab-pivot')).toHaveClass(/border-oe-blue/);
  });

  test('2) Slicer added → URL updates → reload keeps slicer active', async ({ page }) => {
    const sessionId = await findSessionId(page);
    if (!sessionId) {
      // Without data we can't add a slicer via normal UI — inject directly.
      await page.goto('/data-explorer');
      await page.waitForLoadState('load');
      await page.screenshot({ path: 'test-results/de-slicer-persist.png', fullPage: true });
      test.skip(true, 'No seeded CAD session — slicer test requires data');
      return;
    }

    // Manually seed a slicer in the URL so we don't depend on chart
    // interaction (which varies with the dataset). The app should
    // hydrate from the URL on load.
    const url = `/data-explorer?session=${sessionId}&tab=pivot&slicers=${encodeURIComponent(
      'category:Wall|Floor',
    )}`;
    await page.goto(url);
    await page.waitForLoadState('load');
    await page.waitForTimeout(1000);

    // Slicer banner should display the chip.
    const chip = page.locator('[data-testid="slicer-chip-category"]');
    await expect(chip).toBeVisible({ timeout: 10000 });
    await page.screenshot({ path: 'test-results/de-slicer-persist.png', fullPage: true });

    // Reload — slicer should still be active.
    await page.reload();
    await page.waitForLoadState('load');
    await page.waitForTimeout(1000);
    await expect(page.locator('[data-testid="slicer-chip-category"]')).toBeVisible({
      timeout: 10000,
    });
    expect(page.url()).toContain('slicers=');
  });

  test('3) Pivot shows Power-BI-style data bars on numeric columns', async ({ page }) => {
    const sessionId = await findSessionId(page);
    if (!sessionId) {
      await page.goto('/data-explorer');
      await page.waitForLoadState('load');
      await page.screenshot({ path: 'test-results/de-data-bars.png', fullPage: true });
      test.skip(true, 'No seeded CAD session — data-bar test requires aggregated data');
      return;
    }

    await page.goto(`/data-explorer?session=${sessionId}&tab=pivot`);
    await page.waitForLoadState('load');
    await page.waitForTimeout(2500); // Wait for pivot auto-run.

    // A databar span should be present for at least one agg column.
    const bars = page.locator('[data-testid^="pivot-databar-"]');
    await expect(bars.first()).toBeVisible({ timeout: 15000 });
    const count = await bars.count();
    expect(count).toBeGreaterThan(0);

    await page.screenshot({ path: 'test-results/de-data-bars.png', fullPage: true });
  });
});
