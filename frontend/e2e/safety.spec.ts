/**
 * E2E tests — Safety module
 *
 * Covers:
 *  - Safety page loads at /safety
 *  - Dashboard / incident list renders
 *  - "Report Incident" button visible
 *  - Observations tab present
 *  - Page renders without console errors
 */
import { test, expect } from '@playwright/test';
import { login } from './helpers';

// ── Shared setup ────────────────────────────────────────────────────────────

test.beforeEach(async ({ page }) => {
  await login(page);
});

// ── Safety page loads ───────────────────────────────────────────────────────

test('safety page loads at /safety', async ({ page }) => {
  await page.goto('/safety');
  await expect(page).toHaveURL(/\/safety/);
  // Should not redirect to login
  await expect(page).not.toHaveURL(/\/login/);
  // Page heading or breadcrumb contains "Safety"
  await expect(page.getByText('Safety').first()).toBeVisible({ timeout: 15_000 });
});

// ── Dashboard / incident list renders ───────────────────────────────────────

test('safety dashboard renders with stats or content area', async ({ page }) => {
  await page.goto('/safety');
  // The page should have a main content area with either stats cards or a table/list
  const main = page.locator('main');
  await expect(main).toBeVisible({ timeout: 15_000 });

  // Should show either incident stats, a table, or an empty state
  const hasContent = await main
    .locator('table, [role="table"], [class*="card"], [class*="Card"], [class*="empty"]')
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  const hasText = await main
    .getByText(/Incident|Open|Observation|No.*incident|Report/i)
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  expect(hasContent || hasText).toBe(true);
});

// ── "Report Incident" button visible ────────────────────────────────────────

test('"Report Incident" button is visible on safety page', async ({ page }) => {
  await page.goto('/safety');
  await page.waitForLoadState('networkidle');

  // The button text is "Report Incident" — may be in a button or empty state action
  const reportBtn = page.getByRole('button', { name: /Report Incident/i }).first();
  await expect(reportBtn).toBeVisible({ timeout: 15_000 });
});

// ── Observations tab present ────────────────────────────────────────────────

test('observations tab is present on safety page', async ({ page }) => {
  await page.goto('/safety');
  await page.waitForLoadState('networkidle');

  // The safety page has tabs: "Incidents" and "Observations"
  const observationsTab = page.getByText(/Observations/i).first();
  await expect(observationsTab).toBeVisible({ timeout: 15_000 });
});

// ── Incidents tab present ───────────────────────────────────────────────────

test('incidents tab is present on safety page', async ({ page }) => {
  await page.goto('/safety');
  await page.waitForLoadState('networkidle');

  const incidentsTab = page.getByText(/Incidents/i).first();
  await expect(incidentsTab).toBeVisible({ timeout: 15_000 });
});

// ── No console errors ───────────────────────────────────────────────────────

test('safety page renders without console errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('DevTools')) {
      errors.push(msg.text());
    }
  });

  await page.goto('/safety');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2_000);

  expect(page.url()).not.toContain('/login');
  expect(errors).toHaveLength(0);
});
