/**
 * E2E tests — RFI & Submittals modules
 *
 * Covers:
 *  - RFI page loads at /rfi
 *  - RFI list renders (table or card layout)
 *  - "New RFI" button visible
 *  - Submittals page loads at /submittals
 *  - Submittals list renders
 *  - "New Submittal" button visible
 */
import { test, expect } from '@playwright/test';
import { login } from './helpers';

// ── Shared setup ────────────────────────────────────────────────────────────

test.beforeEach(async ({ page }) => {
  await login(page);
});

// ── RFI page loads ──────────────────────────────────────────────────────────

test('RFI page loads at /rfi', async ({ page }) => {
  await page.goto('/rfi');
  await expect(page).toHaveURL(/\/rfi/);
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByText(/RFI/i).first()).toBeVisible({ timeout: 15_000 });
});

// ── RFI list renders ────────────────────────────────────────────────────────

test('RFI list or empty state renders', async ({ page }) => {
  await page.goto('/rfi');
  const main = page.locator('main');
  await expect(main).toBeVisible({ timeout: 15_000 });

  // Should show either a list/table of RFIs or an empty state
  const hasContent = await main
    .locator('table, [role="table"], [class*="card"], [class*="Card"], [class*="empty"]')
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  const hasText = await main
    .getByText(/RFI|No.*request|New RFI|Open|Draft/i)
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  expect(hasContent || hasText).toBe(true);
});

// ── "New RFI" button visible ────────────────────────────────────────────────

test('"New RFI" button is visible on RFI page', async ({ page }) => {
  await page.goto('/rfi');
  await page.waitForLoadState('networkidle');

  const newBtn = page.getByRole('button', { name: /New RFI/i }).first();
  await expect(newBtn).toBeVisible({ timeout: 15_000 });
});

// ── Submittals page loads ───────────────────────────────────────────────────

test('submittals page loads at /submittals', async ({ page }) => {
  await page.goto('/submittals');
  await expect(page).toHaveURL(/\/submittals/);
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByText(/Submittal/i).first()).toBeVisible({ timeout: 15_000 });
});

// ── Submittals list renders ─────────────────────────────────────────────────

test('submittals list or empty state renders', async ({ page }) => {
  await page.goto('/submittals');
  const main = page.locator('main');
  await expect(main).toBeVisible({ timeout: 15_000 });

  const hasContent = await main
    .locator('table, [role="table"], [class*="card"], [class*="Card"], [class*="empty"]')
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  const hasText = await main
    .getByText(/Submittal|No.*submittal|New Submittal|Draft|Submitted/i)
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  expect(hasContent || hasText).toBe(true);
});

// ── "New Submittal" button visible ──────────────────────────────────────────

test('"New Submittal" button is visible on submittals page', async ({ page }) => {
  await page.goto('/submittals');
  await page.waitForLoadState('networkidle');

  const newBtn = page.getByRole('button', { name: /New Submittal/i }).first();
  await expect(newBtn).toBeVisible({ timeout: 15_000 });
});
