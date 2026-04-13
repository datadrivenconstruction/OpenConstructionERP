/**
 * E2E tests — Contacts & Correspondence modules
 *
 * Covers:
 *  - Contacts page loads at /contacts
 *  - Contact list renders
 *  - Correspondence page loads at /correspondence
 *  - Correspondence list renders
 */
import { test, expect } from '@playwright/test';
import { login } from './helpers';

// ── Shared setup ────────────────────────────────────────────────────────────

test.beforeEach(async ({ page }) => {
  await login(page);
});

// ── Contacts page loads ─────────────────────────────────────────────────────

test('contacts page loads at /contacts', async ({ page }) => {
  await page.goto('/contacts');
  await expect(page).toHaveURL(/\/contacts/);
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByText(/Contact/i).first()).toBeVisible({ timeout: 15_000 });
});

// ── Contact list renders ────────────────────────────────────────────────────

test('contact list or empty state renders', async ({ page }) => {
  await page.goto('/contacts');
  const main = page.locator('main');
  await expect(main).toBeVisible({ timeout: 15_000 });

  const hasContent = await main
    .locator('table, [role="table"], [class*="card"], [class*="Card"], [class*="empty"]')
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  const hasText = await main
    .getByText(/Contact|No.*contact|New Contact|Client|Subcontractor|Supplier/i)
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  expect(hasContent || hasText).toBe(true);
});

// ── "New Contact" button visible ────────────────────────────────────────────

test('"New Contact" button is visible on contacts page', async ({ page }) => {
  await page.goto('/contacts');
  await page.waitForLoadState('networkidle');

  const newBtn = page.getByRole('button', { name: /New Contact/i }).first();
  await expect(newBtn).toBeVisible({ timeout: 15_000 });
});

// ── Contact type filters visible ────────────────────────────────────────────

test('contact page shows type filters or search', async ({ page }) => {
  await page.goto('/contacts');
  const main = page.locator('main');
  await expect(main).toBeVisible({ timeout: 15_000 });

  // The contacts page has type filters (client, subcontractor, supplier, consultant)
  // or at least a search input
  const hasFilter = await main
    .getByText(/Client|Subcontractor|Supplier|Consultant/i)
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  const hasSearch = await main
    .locator('input[placeholder*="earch"], input[type="search"]')
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  expect(hasFilter || hasSearch).toBe(true);
});

// ── Correspondence page loads ───────────────────────────────────────────────

test('correspondence page loads at /correspondence', async ({ page }) => {
  await page.goto('/correspondence');
  await expect(page).toHaveURL(/\/correspondence/);
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByText(/Correspondence/i).first()).toBeVisible({ timeout: 15_000 });
});

// ── Correspondence list renders ─────────────────────────────────────────────

test('correspondence list or empty state renders', async ({ page }) => {
  await page.goto('/correspondence');
  const main = page.locator('main');
  await expect(main).toBeVisible({ timeout: 15_000 });

  const hasContent = await main
    .locator('table, [role="table"], [class*="card"], [class*="Card"], [class*="empty"]')
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  const hasText = await main
    .getByText(/Correspondence|No.*correspondence|New Letter|Letter|Email|Notice|Memo/i)
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  expect(hasContent || hasText).toBe(true);
});

// ── "New Letter" button visible ─────────────────────────────────────────────

test('"New Letter" button is visible on correspondence page', async ({ page }) => {
  await page.goto('/correspondence');
  await page.waitForLoadState('networkidle');

  const newBtn = page.getByRole('button', { name: /New Letter/i }).first();
  await expect(newBtn).toBeVisible({ timeout: 15_000 });
});

// ── No console errors on contacts ───────────────────────────────────────────

test('contacts page renders without console errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('DevTools')) {
      errors.push(msg.text());
    }
  });

  await page.goto('/contacts');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2_000);

  expect(page.url()).not.toContain('/login');
  expect(errors).toHaveLength(0);
});

// ── No console errors on correspondence ─────────────────────────────────────

test('correspondence page renders without console errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('DevTools')) {
      errors.push(msg.text());
    }
  });

  await page.goto('/correspondence');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2_000);

  expect(page.url()).not.toContain('/login');
  expect(errors).toHaveLength(0);
});
