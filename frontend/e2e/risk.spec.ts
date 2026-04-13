/**
 * E2E tests — Risk Register module
 *
 * Covers:
 *  - Risk register page loads at /risks
 *  - Risk matrix or list renders
 *  - "Add Risk" button visible
 *  - Risk assessment cards/table visible
 */
import { test, expect } from '@playwright/test';
import { login } from './helpers';

// ── Shared setup ────────────────────────────────────────────────────────────

test.beforeEach(async ({ page }) => {
  await login(page);
});

// ── Risk register page loads ────────────────────────────────────────────────

test('risk register page loads at /risks', async ({ page }) => {
  await page.goto('/risks');
  await expect(page).toHaveURL(/\/risks/);
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByText(/Risk/i).first()).toBeVisible({ timeout: 15_000 });
});

// ── Risk matrix or list renders ─────────────────────────────────────────────

test('risk matrix or list renders on risk page', async ({ page }) => {
  await page.goto('/risks');
  const main = page.locator('main');
  await expect(main).toBeVisible({ timeout: 15_000 });

  // The risk page shows a risk matrix (probability x impact grid) or a list/table
  const hasMatrix = await main
    .getByText(/Probability|Impact|Very High|High|Medium|Low|Critical/i)
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  const hasList = await main
    .locator('table, [role="table"], [class*="card"], [class*="Card"], [class*="empty"]')
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  const hasRiskText = await main
    .getByText(/Risk|No.*risk|Add Risk|Register/i)
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  expect(hasMatrix || hasList || hasRiskText).toBe(true);
});

// ── "Add Risk" button visible ───────────────────────────────────────────────

test('"Add Risk" button is visible on risk page', async ({ page }) => {
  await page.goto('/risks');
  await page.waitForLoadState('networkidle');

  const addBtn = page.getByRole('button', { name: /Add Risk/i }).first();
  await expect(addBtn).toBeVisible({ timeout: 15_000 });
});

// ── Risk categories filter or cards visible ─────────────────────────────────

test('risk page shows category filters or status badges', async ({ page }) => {
  await page.goto('/risks');
  const main = page.locator('main');
  await expect(main).toBeVisible({ timeout: 15_000 });

  // The risk page has category filters (technical, financial, schedule, etc.)
  // or status badges (identified, assessed, mitigating, etc.)
  const hasFilter = await main
    .getByText(/technical|financial|schedule|regulatory|environmental|safety/i)
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  const hasStatus = await main
    .getByText(/identified|assessed|mitigating|closed|occurred/i)
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  const hasSearchOrFilter = await main
    .locator('input[placeholder*="earch"], select, [role="combobox"]')
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  expect(hasFilter || hasStatus || hasSearchOrFilter).toBe(true);
});

// ── No console errors ───────────────────────────────────────────────────────

test('risk page renders without console errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('DevTools')) {
      errors.push(msg.text());
    }
  });

  await page.goto('/risks');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2_000);

  expect(page.url()).not.toContain('/login');
  expect(errors).toHaveLength(0);
});
