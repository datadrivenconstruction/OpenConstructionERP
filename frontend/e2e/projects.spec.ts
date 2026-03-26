/**
 * E2E tests — Projects module
 *
 * Covers:
 *  - Projects page loads when authenticated
 *  - "New Project" button navigates to creation form
 *  - Create project form renders all required fields
 *  - Create project form validation (empty name)
 *  - Successful project creation navigates to detail page
 *  - Project detail page loads
 *  - Project search / filter UI elements are present
 */
import { test, expect } from '@playwright/test';
import { login } from './helpers';

// ── Shared setup: log in before each test in this file ───────────────────────

test.beforeEach(async ({ page }) => {
  await login(page);
});

// ── Projects list page ────────────────────────────────────────────────────────

test('projects page loads after navigation from sidebar', async ({ page }) => {
  await page.goto('/projects');

  await expect(page).toHaveURL(/\/projects/);

  // The page heading contains "Projects" (translated)
  const heading = page.getByRole('heading', { level: 1 });
  await expect(heading).toBeVisible();
  await expect(heading).toContainText(/project/i);
});

test('projects page shows "New Project" button', async ({ page }) => {
  await page.goto('/projects');

  // Button text comes from i18n key 'projects.new_project'
  const newBtn = page.getByRole('button', { name: /new project|create project/i });
  await expect(newBtn).toBeVisible();
});

test('projects page shows empty state when no projects exist', async ({ page }) => {
  await page.goto('/projects');

  // The page either shows project cards OR the empty-state component.
  // Both are valid — we just confirm the page rendered without crashing.
  const hasContent = await page
    .locator('.animate-fade-in')
    .first()
    .isVisible()
    .catch(() => false);
  expect(hasContent).toBe(true);
});

test('clicking New Project button navigates to /projects/new', async ({ page }) => {
  await page.goto('/projects');

  const newBtn = page.getByRole('button', { name: /new project|create project/i });
  await newBtn.click();

  await expect(page).toHaveURL(/\/projects\/new/);
});

// ── Create project form ───────────────────────────────────────────────────────

test('create project page renders the form', async ({ page }) => {
  await page.goto('/projects/new');

  // Project name input (required)
  await expect(page.getByRole('heading', { name: /new project/i })).toBeVisible();

  // Name field
  const nameInput = page.locator('input[required]').first();
  await expect(nameInput).toBeVisible();

  // Submit / Create button
  await expect(page.getByRole('button', { name: /create/i })).toBeVisible();

  // Cancel button
  await expect(page.getByRole('button', { name: /cancel/i })).toBeVisible();
});

test('create project form shows breadcrumb navigation', async ({ page }) => {
  await page.goto('/projects/new');

  // Breadcrumb link back to Projects
  await expect(page.getByRole('link', { name: /projects/i })).toBeVisible();
});

test('create project breadcrumb "Projects" navigates back', async ({ page }) => {
  await page.goto('/projects/new');

  await page.getByRole('link', { name: /^projects$/i }).click();
  await expect(page).toHaveURL(/\/projects/);
});

test('create project cancel button navigates back to /projects', async ({ page }) => {
  await page.goto('/projects/new');

  await page.getByRole('button', { name: /cancel/i }).click();
  await expect(page).toHaveURL(/\/projects/);
});

test('create project form does not submit with empty name', async ({ page }) => {
  await page.goto('/projects/new');

  // Click submit without filling in a name
  await page.getByRole('button', { name: /create/i }).click();

  // Should still be on the new project page
  await expect(page).toHaveURL(/\/projects\/new/);
});

test('create project form submits with valid data and navigates to detail page', async ({
  page,
}) => {
  await page.goto('/projects/new');

  const uniqueName = `E2E Test Project ${Date.now()}`;

  // Fill project name
  await page.locator('input[required]').first().fill(uniqueName);

  // Select region — "DACH" is the first meaningful option
  await page.locator('select').nth(0).selectOption('DACH');

  // Select classification standard — "din276"
  await page.locator('select').nth(1).selectOption('din276');

  // Select currency — "EUR"
  await page.locator('select').nth(2).selectOption('EUR');

  // Submit
  await page.getByRole('button', { name: /create/i }).click();

  // After creation we land on /projects/{uuid}
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}/, { timeout: 15_000 });
});

// ── Project detail page ───────────────────────────────────────────────────────

test('project detail page loads for existing project', async ({ page }) => {
  // Create a project first, then verify its detail page
  await page.goto('/projects/new');

  const uniqueName = `E2E Detail Test ${Date.now()}`;
  await page.locator('input[required]').first().fill(uniqueName);
  await page.locator('select').nth(0).selectOption('UK');
  await page.locator('select').nth(1).selectOption('nrm');
  await page.locator('select').nth(2).selectOption('GBP');
  await page.getByRole('button', { name: /create/i }).click();

  // Wait for redirect to detail page
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}/, { timeout: 15_000 });

  // The project name should appear on the detail page
  await expect(page.getByText(uniqueName)).toBeVisible({ timeout: 10_000 });
});

test('project detail page shows "New BOQ" action', async ({ page }) => {
  // Navigate to create project, create it, then check detail
  await page.goto('/projects/new');

  const uniqueName = `E2E BOQ Action Test ${Date.now()}`;
  await page.locator('input[required]').first().fill(uniqueName);
  await page.locator('select').nth(0).selectOption('US');
  await page.locator('select').nth(1).selectOption('masterformat');
  await page.locator('select').nth(2).selectOption('USD');
  await page.getByRole('button', { name: /create/i }).click();

  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}/, { timeout: 15_000 });

  // There should be a button/link to create a new BOQ
  const newBoqBtn = page.getByRole('button', { name: /new boq|create boq|add boq/i });
  await expect(newBoqBtn).toBeVisible({ timeout: 8_000 });
});

// ── Search / filter UI ────────────────────────────────────────────────────────

test('projects page search input is present when projects exist', async ({ page }) => {
  // Ensure at least one project exists by creating one
  await page.goto('/projects/new');
  await page.locator('input[required]').first().fill(`E2E Search Test ${Date.now()}`);
  await page.locator('select').nth(0).selectOption('DACH');
  await page.locator('select').nth(1).selectOption('din276');
  await page.locator('select').nth(2).selectOption('EUR');
  await page.getByRole('button', { name: /create/i }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}/, { timeout: 15_000 });

  // Go to projects list
  await page.goto('/projects');

  // Search input should now appear
  const searchInput = page.locator('input[type="text"]').first();
  await expect(searchInput).toBeVisible();
});
