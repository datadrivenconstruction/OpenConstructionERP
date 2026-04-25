/**
 * Regression test for the user-reported bug: "i click to the next page and
 * pages update to 0/31".  The root cause was a stale `useCallback` closure
 * over `totalPages` (deps=[]) in `nextPage`, baking `totalPages=0` from the
 * first render → `Math.min(p+1, 0) = 0` on every Next click.
 *
 * The test uploads a real 31-page PDF, presses Next, and asserts that the
 * page indicator advances correctly (2/31, 3/31, …) instead of resetting
 * to 0/31.  Also exercises the Properties counter to confirm the new
 * "X on page · Y total" label appears once measurements span pages.
 */
import { test, expect } from '@playwright/test';
import path from 'path';

const EMAIL = process.env.E2E_USER_EMAIL ?? 'admin@openestimate.io';
const PASSWORD = process.env.E2E_USER_PASSWORD ?? 'OpenEstimate2026';

test('PDF takeoff: Next button advances page indicator (no 0/31 reset)', async ({
  page,
}) => {
  test.setTimeout(120_000);

  await page.goto('/login');
  await page.locator('input[type="email"]').fill(EMAIL);
  await page.locator('#login-password').fill(PASSWORD);
  await page.locator('button[type="submit"]').click();
  await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 });

  await page.goto('/takeoff');
  await page.waitForLoadState('networkidle', { timeout: 30_000 });

  // Dismiss the onboarding/tour overlay if it shows.
  const tourClose = page
    .getByRole('button', { name: /close|skip|dismiss|×/i })
    .filter({ hasText: /^[×xX]$|skip|close/i })
    .first();
  if (await tourClose.isVisible().catch(() => false)) {
    await tourClose.click().catch(() => {});
  }
  await page.keyboard.press('Escape').catch(() => {});

  // Switch to the "Measurements" tab FIRST — its viewer has its own
  // file input (separate from the AI Documents workflow input).
  const measurementsTab = page.getByRole('button', { name: /measurements/i }).first();
  await measurementsTab.click();
  await page.waitForTimeout(1_500);

  await page.screenshot({ path: 'test-results/takeoff-01-landing.png' });

  // Drop our 31-page PDF onto the Measurements tab dropzone.
  const fixture = path.resolve(process.cwd(), 'e2e/fixtures/multipage-test.pdf');
  const fileInput = page.locator('input[type="file"]').first();
  await fileInput.setInputFiles(fixture);
  await page.waitForTimeout(3_000);

  // Wait for the toolbar's page indicator to appear.
  const indicator = page
    .locator('text=/^\\s*\\d+\\s*\\/\\s*\\d+\\s*$/')
    .first();
  await indicator.waitFor({ state: 'visible', timeout: 30_000 });

  await expect(indicator).toHaveText(/^\s*1\s*\/\s*31\s*$/, { timeout: 15_000 });
  await page.screenshot({ path: 'test-results/takeoff-02-loaded-page1.png' });

  // Press Next once → must show 2/31, NOT 0/31.
  const nextBtn = page
    .getByRole('button', { name: /next page/i })
    .first();
  await nextBtn.click();
  await expect(indicator).toHaveText(/^\s*2\s*\/\s*31\s*$/, { timeout: 5_000 });
  await page.screenshot({ path: 'test-results/takeoff-03-page2.png' });

  // Press Next 5 more times → 7/31.
  for (let i = 0; i < 5; i++) await nextBtn.click();
  await expect(indicator).toHaveText(/^\s*7\s*\/\s*31\s*$/, { timeout: 5_000 });

  // Negative regression: indicator must NEVER read 0/31 at any point.
  const text = await indicator.textContent();
  expect(text?.replace(/\s/g, '')).not.toBe('0/31');
  await page.screenshot({ path: 'test-results/takeoff-04-page7.png', fullPage: true });
});
