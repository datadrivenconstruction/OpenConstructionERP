/**
 * E2E tests — Documents & Tasks modules
 *
 * Covers:
 *  - Documents page loads at /documents
 *  - Document list renders
 *  - Upload area visible
 *  - Tasks page loads at /tasks
 *  - Task list renders
 *  - "New Task" button visible
 */
import { test, expect } from '@playwright/test';
import { login } from './helpers';

// ── Shared setup ────────────────────────────────────────────────────────────

test.beforeEach(async ({ page }) => {
  await login(page);
});

// ── Documents page loads ────────────────────────────────────────────────────

test('documents page loads at /documents', async ({ page }) => {
  await page.goto('/documents');
  await expect(page).toHaveURL(/\/documents/);
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByText(/Document/i).first()).toBeVisible({ timeout: 15_000 });
});

// ── Document list renders ───────────────────────────────────────────────────

test('document list or empty state renders', async ({ page }) => {
  await page.goto('/documents');
  const main = page.locator('main');
  await expect(main).toBeVisible({ timeout: 15_000 });

  const hasContent = await main
    .locator('table, [role="table"], [class*="card"], [class*="Card"], [class*="empty"]')
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  const hasText = await main
    .getByText(/Document|No.*document|Upload|drawing|contract|specification/i)
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  expect(hasContent || hasText).toBe(true);
});

// ── Upload area visible ─────────────────────────────────────────────────────

test('upload button or drop zone is visible on documents page', async ({ page }) => {
  await page.goto('/documents');
  await page.waitForLoadState('networkidle');

  // The documents page should have an upload button or a drag-and-drop zone
  const hasUploadBtn = await page
    .getByRole('button', { name: /Upload/i })
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  const hasDropZone = await page
    .locator('[class*="drop"], [class*="upload"], input[type="file"]')
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  const hasUploadText = await page
    .getByText(/Upload|Drop.*file|drag.*drop/i)
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  expect(hasUploadBtn || hasDropZone || hasUploadText).toBe(true);
});

// ── Tasks page loads ────────────────────────────────────────────────────────

test('tasks page loads at /tasks', async ({ page }) => {
  await page.goto('/tasks');
  await expect(page).toHaveURL(/\/tasks/);
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByText(/Task/i).first()).toBeVisible({ timeout: 15_000 });
});

// ── Task list renders ───────────────────────────────────────────────────────

test('task list or empty state renders', async ({ page }) => {
  await page.goto('/tasks');
  const main = page.locator('main');
  await expect(main).toBeVisible({ timeout: 15_000 });

  const hasContent = await main
    .locator('table, [role="table"], [class*="card"], [class*="Card"], [class*="empty"]')
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  const hasText = await main
    .getByText(/Task|No.*task|New Task|Open|Draft|Completed/i)
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  expect(hasContent || hasText).toBe(true);
});

// ── "New Task" button visible ───────────────────────────────────────────────

test('"New Task" button is visible on tasks page', async ({ page }) => {
  await page.goto('/tasks');
  await page.waitForLoadState('networkidle');

  const newBtn = page.getByRole('button', { name: /New Task/i }).first();
  await expect(newBtn).toBeVisible({ timeout: 15_000 });
});

// ── No console errors on documents ──────────────────────────────────────────

test('documents page renders without console errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('DevTools')) {
      errors.push(msg.text());
    }
  });

  await page.goto('/documents');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2_000);

  expect(page.url()).not.toContain('/login');
  expect(errors).toHaveLength(0);
});

// ── No console errors on tasks ──────────────────────────────────────────────

test('tasks page renders without console errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('DevTools')) {
      errors.push(msg.text());
    }
  });

  await page.goto('/tasks');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2_000);

  expect(page.url()).not.toContain('/login');
  expect(errors).toHaveLength(0);
});
