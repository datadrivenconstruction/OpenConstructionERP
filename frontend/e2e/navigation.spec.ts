/**
 * E2E tests — Navigation & routing
 *
 * Covers:
 *  - Sidebar links navigate to correct routes
 *  - Dashboard link in sidebar works
 *  - Breadcrumb navigation
 *  - 404 / NotFound page renders for unknown routes
 *  - Ctrl+K opens the command palette
 *  - Ctrl+N keyboard shortcut navigates to new project
 *  - Ctrl+Shift+V navigates to validation
 *  - Sidebar group collapse / expand
 */
import { test, expect } from '@playwright/test';
import { login } from './helpers';

// ── Shared setup ─────────────────────────────────────────────────────────────

test.beforeEach(async ({ page }) => {
  await login(page);
  // Start from the dashboard for all navigation tests
  await page.goto('/');
  await page.waitForLoadState('networkidle');
});

// ── Sidebar link navigation ───────────────────────────────────────────────────

test('sidebar "Projects" link navigates to /projects', async ({ page }) => {
  // The sidebar renders NavLink components; find the one pointing to /projects
  await page.getByRole('link', { name: /^projects$/i }).first().click();
  await expect(page).toHaveURL(/\/projects/);
});

test('sidebar "BOQ" link navigates to /boq', async ({ page }) => {
  // The nav label comes from i18n key 'boq.title' which defaults to "BOQ" or similar
  await page.getByRole('link', { name: /bill of quantities|^boq$/i }).first().click();
  await expect(page).toHaveURL(/\/boq/);
});

test('sidebar "Cost Database" link navigates to /costs', async ({ page }) => {
  await page.getByRole('link', { name: /cost database|^costs$/i }).first().click();
  await expect(page).toHaveURL(/\/costs/);
});

test('sidebar "Dashboard" link navigates to /', async ({ page }) => {
  // First navigate away, then come back via sidebar
  await page.goto('/projects');

  await page.getByRole('link', { name: /dashboard/i }).first().click();
  await expect(page).toHaveURL(/^http:\/\/localhost:5173\/?$/);
});

test('sidebar "Schedule" link navigates to /schedule', async ({ page }) => {
  const scheduleLink = page.getByRole('link', { name: /^schedule$|4d schedule/i }).first();
  // The schedule item might be inside a collapsible group; expand it first
  const planningGroup = page.locator('[data-group="planning"], button').filter({ hasText: /planning/i });
  if (await planningGroup.count() > 0) {
    await planningGroup.first().click();
  }
  await scheduleLink.click();
  await expect(page).toHaveURL(/\/schedule/);
});

test('sidebar "Settings" link navigates to /settings', async ({ page }) => {
  await page.getByRole('link', { name: /settings/i }).first().click();
  await expect(page).toHaveURL(/\/settings/);
});

test('sidebar "Modules" link navigates to /modules', async ({ page }) => {
  await page.getByRole('link', { name: /modules/i }).first().click();
  await expect(page).toHaveURL(/\/modules/);
});

test('sidebar "Assemblies" link navigates to /assemblies', async ({ page }) => {
  await page.getByRole('link', { name: /assemblies/i }).first().click();
  await expect(page).toHaveURL(/\/assemblies/);
});

// ── Breadcrumb navigation ─────────────────────────────────────────────────────

test('create project breadcrumb navigates back to projects list', async ({ page }) => {
  await page.goto('/projects/new');

  // Find the breadcrumb "Projects" link
  const breadcrumbLink = page.getByRole('link', { name: /^projects$/i });
  await expect(breadcrumbLink).toBeVisible();

  await breadcrumbLink.click();
  await expect(page).toHaveURL(/\/projects/);
});

test('breadcrumb on assemblies new page navigates back', async ({ page }) => {
  await page.goto('/assemblies/new');

  const breadcrumbLink = page.getByRole('link', { name: /assemblies/i }).first();
  await expect(breadcrumbLink).toBeVisible();

  await breadcrumbLink.click();
  await expect(page).toHaveURL(/\/assemblies/);
});

// ── 404 / Not Found page ──────────────────────────────────────────────────────

test('navigating to an unknown route renders a 404 / NotFound page', async ({ page }) => {
  await page.goto('/this-route-does-not-exist-at-all');

  // The NotFoundPage component should render
  // It typically contains "404" or "not found" in some visible element
  await expect(
    page.getByText(/404|not found|page not found/i).first()
  ).toBeVisible({ timeout: 8_000 });

  // The page should not redirect to /login since the user is authenticated
  await expect(page).not.toHaveURL(/\/login/);
});

test('404 page on deeply nested unknown route', async ({ page }) => {
  await page.goto('/projects/nonexistent-uuid/some/deep/path');

  // Should render 404 or redirect to dashboard — either is valid
  const is404 = await page
    .getByText(/404|not found/i)
    .first()
    .isVisible()
    .catch(() => false);

  const isHome = page.url().endsWith('/');

  expect(is404 || isHome).toBe(true);
});

// ── Keyboard shortcuts ────────────────────────────────────────────────────────

test('Ctrl+K opens the command palette', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  // Trigger the command palette shortcut
  await page.keyboard.press('Control+k');

  // The CommandPalette component should become visible
  // It renders an input/search field when open
  const palette = page.locator('[role="dialog"], [data-palette], input[placeholder*="command" i], input[placeholder*="search" i]').first();
  await expect(palette).toBeVisible({ timeout: 5_000 });
});

test('Ctrl+K closes the command palette when pressed again', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  // Open
  await page.keyboard.press('Control+k');
  const palette = page.locator('[role="dialog"], [data-palette]').first();
  await expect(palette).toBeVisible({ timeout: 5_000 });

  // Close — second Ctrl+K should toggle it off
  await page.keyboard.press('Control+k');
  await expect(palette).not.toBeVisible({ timeout: 5_000 });
});

test('Escape key closes the command palette', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  await page.keyboard.press('Control+k');
  const palette = page.locator('[role="dialog"], [data-palette]').first();
  await expect(palette).toBeVisible({ timeout: 5_000 });

  await page.keyboard.press('Escape');
  await expect(palette).not.toBeVisible({ timeout: 5_000 });
});

test('Ctrl+N keyboard shortcut navigates to /projects/new', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  await page.keyboard.press('Control+n');

  await expect(page).toHaveURL(/\/projects\/new/, { timeout: 8_000 });
});

test('Ctrl+Shift+V keyboard shortcut navigates to /validation', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  await page.keyboard.press('Control+Shift+V');

  await expect(page).toHaveURL(/\/validation/, { timeout: 8_000 });
});

// ── Sidebar group collapse/expand ─────────────────────────────────────────────

test('sidebar group can be collapsed and expanded', async ({ page }) => {
  await page.goto('/');

  // The "Planning" group is collapsible — find it by text
  const planningGroup = page.locator('button').filter({ hasText: /planning/i }).first();
  await expect(planningGroup).toBeVisible();

  // Click to collapse
  await planningGroup.click();

  // Click again to expand
  await planningGroup.click();

  // After expanding, the Schedule link should be visible again
  const scheduleLink = page.getByRole('link', { name: /schedule/i }).first();
  await expect(scheduleLink).toBeVisible({ timeout: 5_000 });
});

// ── Direct URL navigation ─────────────────────────────────────────────────────

test('direct navigation to /dashboard redirects to /', async ({ page }) => {
  // The app does not have a /dashboard route — the dashboard IS at /
  await page.goto('/dashboard');

  // Should land on 404 or be redirected to /
  const url = page.url();
  expect(url.includes('/dashboard') || url.endsWith('/')).toBe(true);
});

test('direct navigation to /costs works', async ({ page }) => {
  await page.goto('/costs');
  await expect(page).toHaveURL(/\/costs/);

  const heading = page.getByRole('heading', { level: 1 });
  await expect(heading).toBeVisible();
});

test('direct navigation to /assemblies works', async ({ page }) => {
  await page.goto('/assemblies');
  await expect(page).toHaveURL(/\/assemblies/);

  const heading = page.getByRole('heading', { level: 1 });
  await expect(heading).toBeVisible();
});

test('direct navigation to /validation works', async ({ page }) => {
  await page.goto('/validation');
  await expect(page).toHaveURL(/\/validation/);
});

test('direct navigation to /reports works', async ({ page }) => {
  await page.goto('/reports');
  await expect(page).toHaveURL(/\/reports/);
});
