/**
 * E2E tests — Settings & Modules pages
 *
 * Covers:
 *  - Settings page loads at /settings
 *  - Language selector visible
 *  - Theme toggle visible
 *  - Modules page loads at /modules
 *  - Module cards render
 */
import { test, expect } from '@playwright/test';
import { login } from './helpers';

// ── Shared setup ────────────────────────────────────────────────────────────

test.beforeEach(async ({ page }) => {
  await login(page);
});

// ── Settings page loads ─────────────────────────────────────────────────────

test('settings page loads at /settings', async ({ page }) => {
  await page.goto('/settings');
  await expect(page).toHaveURL(/\/settings/);
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByText(/Settings/i).first()).toBeVisible({ timeout: 15_000 });
});

// ── Language selector visible ───────────────────────────────────────────────

test('language selector is visible on settings page', async ({ page }) => {
  await page.goto('/settings');
  await page.waitForLoadState('networkidle');

  // The settings page has a "Language & Region" section with language options
  const hasLangSection = await page
    .getByText(/Language/i)
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  // Language buttons/selectors should be visible (e.g., English, Deutsch, etc.)
  const hasLangOption = await page
    .getByText(/English|Deutsch|Fran|Espa/i)
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  expect(hasLangSection || hasLangOption).toBe(true);
});

// ── Theme toggle visible ────────────────────────────────────────────────────

test('theme toggle is visible on settings page', async ({ page }) => {
  await page.goto('/settings');
  await page.waitForLoadState('networkidle');

  // The settings page has theme options: Light, Dark, System
  const hasThemeOption = await page
    .getByText(/Light|Dark|System/i)
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  const hasThemeButton = await page
    .getByRole('button', { name: /Light|Dark|System/i })
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  expect(hasThemeOption || hasThemeButton).toBe(true);
});

// ── Settings page has profile section ───────────────────────────────────────

test('settings page shows user profile or account section', async ({ page }) => {
  await page.goto('/settings');
  const main = page.locator('main');
  await expect(main).toBeVisible({ timeout: 15_000 });

  // Settings page should have profile/account info
  const hasProfile = await main
    .getByText(/Profile|Account|Email|Name/i)
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  expect(hasProfile).toBe(true);
});

// ── Modules page loads ──────────────────────────────────────────────────────

test('modules page loads at /modules', async ({ page }) => {
  await page.goto('/modules');
  await expect(page).toHaveURL(/\/modules/);
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByText(/Module/i).first()).toBeVisible({ timeout: 15_000 });
});

// ── Module cards render ─────────────────────────────────────────────────────

test('module cards or list renders on modules page', async ({ page }) => {
  await page.goto('/modules');
  const main = page.locator('main');
  await expect(main).toBeVisible({ timeout: 15_000 });

  // The modules page shows cards for installed/available modules
  const hasCards = await main
    .locator('[class*="card"], [class*="Card"], [class*="grid"]')
    .first()
    .isVisible({ timeout: 10_000 })
    .catch(() => false);

  const hasModuleText = await main
    .getByText(/Module|Installed|Available|Core|Plugin|Enabled/i)
    .first()
    .isVisible({ timeout: 5_000 })
    .catch(() => false);

  expect(hasCards || hasModuleText).toBe(true);
});

// ── No console errors on settings ───────────────────────────────────────────

test('settings page renders without console errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('DevTools')) {
      errors.push(msg.text());
    }
  });

  await page.goto('/settings');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2_000);

  expect(page.url()).not.toContain('/login');
  expect(errors).toHaveLength(0);
});

// ── No console errors on modules ────────────────────────────────────────────

test('modules page renders without console errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('DevTools')) {
      errors.push(msg.text());
    }
  });

  await page.goto('/modules');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2_000);

  expect(page.url()).not.toContain('/login');
  expect(errors).toHaveLength(0);
});
