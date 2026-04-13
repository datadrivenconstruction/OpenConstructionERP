/**
 * E2E tests — Change Orders & Finance modules
 *
 * Covers:
 *  - Change orders page loads at /changeorders
 *  - Change orders list renders
 *  - "New Change Order" button visible
 *  - Finance page loads at /finance
 *  - Finance dashboard renders with tabs (Budgets / Invoices)
 */
import { test, expect } from '@playwright/test';
import { login } from './helpers';

// ── Shared setup ────────────────────────────────────────────────────────────

test.beforeEach(async ({ page }) => {
  await login(page);
});

// ── Change orders page loads ────────────────────────────────────────────────

test('change orders page loads at /changeorders', async ({ page }) => {
  await page.goto('/changeorders');
  await expect(page).toHaveURL(/\/changeorders/);
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByText(/Change Order/i).first()).toBeVisible({ timeout: 15_000 });
});

// ── Change orders list renders ──────────────────────────────────────────────

test('change orders list or empty state renders', async ({ page }) => {
  await page.goto('/changeorders');
  const main = page.locator('main');
  await expect(main).toBeVisible({ timeout: 15_000 });

  const hasContent = await main
    .locator('table, [role="table"], [class*="card"], [class*="Card"], [class*="empty"]')
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  const hasText = await main
    .getByText(/Change Order|No.*change|New Change Order|Draft|Approved/i)
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  expect(hasContent || hasText).toBe(true);
});

// ── "New Change Order" button visible ───────────────────────────────────────

test('"New Change Order" button is visible', async ({ page }) => {
  await page.goto('/changeorders');
  await page.waitForLoadState('networkidle');

  const newBtn = page.getByRole('button', { name: /New Change Order/i }).first();
  await expect(newBtn).toBeVisible({ timeout: 15_000 });
});

// ── Finance page loads ──────────────────────────────────────────────────────

test('finance page loads at /finance', async ({ page }) => {
  await page.goto('/finance');
  await expect(page).toHaveURL(/\/finance/);
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByText(/Finance/i).first()).toBeVisible({ timeout: 15_000 });
});

// ── Finance dashboard renders with KPIs / tabs ──────────────────────────────

test('finance dashboard renders with budget or invoice tabs', async ({ page }) => {
  await page.goto('/finance');
  const main = page.locator('main');
  await expect(main).toBeVisible({ timeout: 15_000 });

  // Finance page has tabs: Budgets, Invoices
  const hasBudgets = await main
    .getByText(/Budget/i)
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  const hasInvoices = await main
    .getByText(/Invoice/i)
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  const hasFinanceContent = await main
    .getByText(/Finance|Budgets|Invoices|Payments|earned value/i)
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  expect(hasBudgets || hasInvoices || hasFinanceContent).toBe(true);
});

// ── No console errors on change orders ──────────────────────────────────────

test('change orders page renders without console errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('DevTools')) {
      errors.push(msg.text());
    }
  });

  await page.goto('/changeorders');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2_000);

  expect(page.url()).not.toContain('/login');
  expect(errors).toHaveLength(0);
});

// ── No console errors on finance ────────────────────────────────────────────

test('finance page renders without console errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('DevTools')) {
      errors.push(msg.text());
    }
  });

  await page.goto('/finance');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2_000);

  expect(page.url()).not.toContain('/login');
  expect(errors).toHaveLength(0);
});
