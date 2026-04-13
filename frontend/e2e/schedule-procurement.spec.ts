/**
 * E2E tests — Schedule & Procurement modules
 *
 * Covers:
 *  - Schedule page loads at /schedule
 *  - Gantt chart or timeline renders
 *  - Procurement page loads at /procurement
 *  - PO list renders
 */
import { test, expect } from '@playwright/test';
import { login } from './helpers';

// ── Shared setup ────────────────────────────────────────────────────────────

test.beforeEach(async ({ page }) => {
  await login(page);
});

// ── Schedule page loads ─────────────────────────────────────────────────────

test('schedule page loads at /schedule', async ({ page }) => {
  await page.goto('/schedule');
  await expect(page).toHaveURL(/\/schedule/);
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByText(/Schedule/i).first()).toBeVisible({ timeout: 15_000 });
});

// ── Gantt chart or timeline renders ─────────────────────────────────────────

test('schedule page renders gantt chart or timeline content', async ({ page }) => {
  await page.goto('/schedule');
  const main = page.locator('main');
  await expect(main).toBeVisible({ timeout: 15_000 });

  // The schedule page shows a Gantt chart (SVG/Canvas), timeline, or activity list
  const hasGantt = await main
    .locator('svg, canvas, [class*="gantt"], [class*="Gantt"], [class*="timeline"]')
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  const hasScheduleContent = await main
    .getByText(/Activity|Task|Milestone|Critical Path|Duration|Gantt|Schedule|No.*schedule/i)
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  const hasList = await main
    .locator('table, [role="table"], [class*="card"], [class*="Card"], [class*="empty"]')
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  expect(hasGantt || hasScheduleContent || hasList).toBe(true);
});

// ── Procurement page loads ──────────────────────────────────────────────────

test('procurement page loads at /procurement', async ({ page }) => {
  await page.goto('/procurement');
  await expect(page).toHaveURL(/\/procurement/);
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByText(/Procurement/i).first()).toBeVisible({ timeout: 15_000 });
});

// ── PO list renders ─────────────────────────────────────────────────────────

test('procurement page renders PO list or empty state', async ({ page }) => {
  await page.goto('/procurement');
  const main = page.locator('main');
  await expect(main).toBeVisible({ timeout: 15_000 });

  const hasContent = await main
    .locator('table, [role="table"], [class*="card"], [class*="Card"], [class*="empty"]')
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  const hasText = await main
    .getByText(/Purchase Order|PO|No.*order|New Purchase|Vendor|Supplier/i)
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  expect(hasContent || hasText).toBe(true);
});

// ── "New Purchase Order" button visible ─────────────────────────────────────

test('"New Purchase Order" button is visible on procurement page', async ({ page }) => {
  await page.goto('/procurement');
  await page.waitForLoadState('networkidle');

  const newBtn = page.getByRole('button', { name: /New Purchase Order/i }).first();
  await expect(newBtn).toBeVisible({ timeout: 15_000 });
});

// ── No console errors on schedule ───────────────────────────────────────────

test('schedule page renders without console errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('DevTools')) {
      errors.push(msg.text());
    }
  });

  await page.goto('/schedule');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2_000);

  expect(page.url()).not.toContain('/login');
  expect(errors).toHaveLength(0);
});

// ── No console errors on procurement ────────────────────────────────────────

test('procurement page renders without console errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('DevTools')) {
      errors.push(msg.text());
    }
  });

  await page.goto('/procurement');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2_000);

  expect(page.url()).not.toContain('/login');
  expect(errors).toHaveLength(0);
});
