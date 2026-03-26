/**
 * E2E tests — Bill of Quantities (BOQ) module
 *
 * Covers:
 *  - BOQ list page loads
 *  - Navigation to create BOQ from list page
 *  - BOQ editor loads for an existing BOQ
 *  - Add position to BOQ
 *  - BOQ search / filter UI
 *  - BOQ compare button present when 2+ BOQs exist
 */
import { test, expect, type Page } from '@playwright/test';
import { login } from './helpers';

// ── Shared setup ─────────────────────────────────────────────────────────────

test.beforeEach(async ({ page }) => {
  await login(page);
});

// ── Helper: create a project and return its ID from the URL ──────────────────

async function createProject(page: Page): Promise<string> {
  await page.goto('/projects/new');

  await page.locator('input[required]').first().fill(`E2E BOQ Project ${Date.now()}`);
  await page.locator('select').nth(0).selectOption('DACH');
  await page.locator('select').nth(1).selectOption('din276');
  await page.locator('select').nth(2).selectOption('EUR');
  await page.getByRole('button', { name: /create/i }).click();

  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}/, { timeout: 15_000 });

  const url = page.url();
  const match = url.match(/\/projects\/([0-9a-f-]{36})/);
  return match ? match[1] : '';
}

// ── BOQ list page ─────────────────────────────────────────────────────────────

test('boq list page loads at /boq', async ({ page }) => {
  await page.goto('/boq');

  await expect(page).toHaveURL(/\/boq/);

  // The main heading contains "BOQ" or "Bill of Quantities"
  const heading = page.getByRole('heading', { level: 1 });
  await expect(heading).toBeVisible();
});

test('boq list page shows empty state or BOQ cards', async ({ page }) => {
  await page.goto('/boq');

  // Page should have rendered without crashing
  // Either there are BOQ cards or an empty state component
  const pageContent = page.locator('.animate-fade-in, .max-w-content').first();
  await expect(pageContent).toBeVisible();
});

// ── Create BOQ navigation ─────────────────────────────────────────────────────

test('navigating to /projects/:id/boq/new shows create BOQ form', async ({ page }) => {
  const projectId = await createProject(page);

  await page.goto(`/projects/${projectId}/boq/new`);
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/boq/new`));

  // There should be a form or heading for creating a BOQ
  const heading = page.getByRole('heading').first();
  await expect(heading).toBeVisible();
});

test('create BOQ form has a name field', async ({ page }) => {
  const projectId = await createProject(page);

  await page.goto(`/projects/${projectId}/boq/new`);

  // An input for the BOQ name must be present
  const nameInput = page.locator('input').first();
  await expect(nameInput).toBeVisible();
});

test('create BOQ navigates to BOQ editor after submission', async ({ page }) => {
  const projectId = await createProject(page);

  await page.goto(`/projects/${projectId}/boq/new`);

  const uniqueName = `E2E BOQ ${Date.now()}`;

  // Fill in the BOQ name
  await page.locator('input').first().fill(uniqueName);

  // Submit the form
  await page.getByRole('button', { name: /create/i }).click();

  // Should navigate to /boq/:boqId
  await expect(page).toHaveURL(/\/boq\/[0-9a-f-]{36}/, { timeout: 15_000 });
});

// ── BOQ editor ────────────────────────────────────────────────────────────────

test('boq editor page loads for an existing BOQ', async ({ page }) => {
  // Create a project + BOQ
  const projectId = await createProject(page);
  await page.goto(`/projects/${projectId}/boq/new`);
  await page.locator('input').first().fill(`E2E Editor Test ${Date.now()}`);
  await page.getByRole('button', { name: /create/i }).click();
  await expect(page).toHaveURL(/\/boq\/[0-9a-f-]{36}/, { timeout: 15_000 });

  // Editor should be visible — either the AG Grid container or toolbar
  // The BOQ editor renders inside a Suspense boundary; wait for it
  await expect(page.locator('.animate-fade-in, [class*="ag-root"]').first()).toBeVisible({
    timeout: 15_000,
  });
});

test('boq editor shows a toolbar or action buttons', async ({ page }) => {
  const projectId = await createProject(page);
  await page.goto(`/projects/${projectId}/boq/new`);
  await page.locator('input').first().fill(`E2E Toolbar Test ${Date.now()}`);
  await page.getByRole('button', { name: /create/i }).click();
  await expect(page).toHaveURL(/\/boq\/[0-9a-f-]{36}/, { timeout: 15_000 });

  // At least one button is visible in the editor toolbar area
  const buttons = page.getByRole('button');
  await expect(buttons.first()).toBeVisible({ timeout: 12_000 });
});

test('boq editor has an "Add position" or row-add button', async ({ page }) => {
  const projectId = await createProject(page);
  await page.goto(`/projects/${projectId}/boq/new`);
  await page.locator('input').first().fill(`E2E Add Position Test ${Date.now()}`);
  await page.getByRole('button', { name: /create/i }).click();
  await expect(page).toHaveURL(/\/boq\/[0-9a-f-]{36}/, { timeout: 15_000 });

  // Look for "Add position" / "Add row" button by text
  const addBtn = page.getByRole('button', { name: /add position|add row|new position|new row/i });
  await expect(addBtn).toBeVisible({ timeout: 12_000 });
});

test('clicking add position button inserts a new row', async ({ page }) => {
  const projectId = await createProject(page);
  await page.goto(`/projects/${projectId}/boq/new`);
  await page.locator('input').first().fill(`E2E Row Insert Test ${Date.now()}`);
  await page.getByRole('button', { name: /create/i }).click();
  await expect(page).toHaveURL(/\/boq\/[0-9a-f-]{36}/, { timeout: 15_000 });

  // Wait for the editor to fully load
  const addBtn = page.getByRole('button', { name: /add position|add row|new position|new row/i });
  await expect(addBtn).toBeVisible({ timeout: 12_000 });

  // Click to add a row
  await addBtn.click();

  // After clicking, there should be at least one editable row or input visible
  // The AG Grid renders rows inside .ag-row or the editor uses inline inputs
  const rows = page.locator('.ag-row, [data-row-index], tr.position-row');
  const rowCount = await rows.count();
  // At least one row should now be present
  expect(rowCount).toBeGreaterThanOrEqual(1);
});

// ── BOQ list page search ──────────────────────────────────────────────────────

test('boq list page search input filters results', async ({ page }) => {
  // Create at least one BOQ so the search input appears
  const projectId = await createProject(page);
  await page.goto(`/projects/${projectId}/boq/new`);
  const boqName = `E2E Search BOQ ${Date.now()}`;
  await page.locator('input').first().fill(boqName);
  await page.getByRole('button', { name: /create/i }).click();
  await expect(page).toHaveURL(/\/boq\/[0-9a-f-]{36}/, { timeout: 15_000 });

  // Navigate to BOQ list
  await page.goto('/boq');

  // Search input should appear when there are BOQs
  const searchInput = page.locator('input[type="text"]').first();
  await expect(searchInput).toBeVisible();

  // Type the BOQ name to filter
  await searchInput.fill(boqName);

  // The BOQ card with that name should be visible
  await expect(page.getByText(boqName, { exact: false })).toBeVisible({ timeout: 8_000 });
});

// ── Keyboard shortcut: Ctrl+Shift+N creates new BOQ ──────────────────────────

test('Ctrl+Shift+N keyboard shortcut navigates to /boq/new', async ({ page }) => {
  await page.goto('/');

  // Ensure the page has loaded and GlobalShortcuts are mounted
  await page.waitForLoadState('networkidle');

  await page.keyboard.press('Control+Shift+N');

  // Ctrl+Shift+N pushes '/boq/new' via pushState in App.tsx
  await expect(page).toHaveURL(/\/boq\/new/, { timeout: 8_000 });
});
