/**
 * E2E tests — Authentication flows
 *
 * Covers:
 *  - Login page renders correctly
 *  - Successful login with valid credentials
 *  - Validation for empty / short fields
 *  - Logout flow
 *  - Redirect from protected route to login when unauthenticated
 *  - "Forgot password" link navigation
 *  - "Create account" link navigation
 */
import { test, expect } from '@playwright/test';
import { login, logout, TEST_USER } from './helpers';

// ── Login page renders ────────────────────────────────────────────────────────

test('login page loads and shows all expected elements', async ({ page }) => {
  await page.goto('/login');

  // URL should be /login
  await expect(page).toHaveURL(/\/login/);

  // Email input
  await expect(page.locator('input[type="email"]')).toBeVisible();

  // Password input (id="login-password" per LoginPage.tsx)
  await expect(page.locator('#login-password')).toBeVisible();

  // Submit button contains "Sign in" text (translated via i18n)
  await expect(page.locator('button[type="submit"]')).toBeVisible();

  // "Forgot password?" link
  await expect(page.getByRole('link', { name: /forgot password/i })).toBeVisible();

  // "Create account" link
  await expect(page.getByRole('link', { name: /create account/i })).toBeVisible();
});

test('login page shows the OpenEstimate logo', async ({ page }) => {
  await page.goto('/login');

  // The LogoWithText component renders inside the form panel
  // We check for the SVG/image or the logo wrapper
  const logoArea = page.locator('.flex.flex-col.items-center');
  await expect(logoArea.first()).toBeVisible();
});

// ── Successful login ──────────────────────────────────────────────────────────

test('successful login redirects away from /login', async ({ page }) => {
  await page.goto('/login');

  await page.locator('input[type="email"]').fill(TEST_USER.email);
  await page.locator('#login-password').fill(TEST_USER.password);
  await page.locator('button[type="submit"]').click();

  // After successful login the app navigates to '/' (dashboard) or '/onboarding'
  await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 });
});

test('authenticated user visiting /login is redirected to dashboard', async ({ page }) => {
  // Log in first
  await login(page);

  // Now navigate to /login — the app should redirect away
  await page.goto('/login');
  await expect(page).not.toHaveURL(/\/login/, { timeout: 8_000 });
});

// ── Form validation ───────────────────────────────────────────────────────────

test('login form shows HTML5 validation for empty email', async ({ page }) => {
  await page.goto('/login');

  // Leave email empty, fill password, try to submit
  await page.locator('#login-password').fill('somepassword');
  await page.locator('button[type="submit"]').click();

  // The email input should have the `required` attribute → browser prevents submit
  // The page should still be on /login
  await expect(page).toHaveURL(/\/login/);
});

test('login form shows HTML5 validation for empty password', async ({ page }) => {
  await page.goto('/login');

  await page.locator('input[type="email"]').fill('test@example.com');
  // Leave password empty
  await page.locator('button[type="submit"]').click();

  // Page stays on /login because password is required
  await expect(page).toHaveURL(/\/login/);
});

test('login form shows HTML5 validation for short password', async ({ page }) => {
  await page.goto('/login');

  await page.locator('input[type="email"]').fill('test@example.com');
  await page.locator('#login-password').fill('short'); // less than minLength=8
  await page.locator('button[type="submit"]').click();

  // Stay on /login — minLength prevents submission
  await expect(page).toHaveURL(/\/login/);
});

test('login form shows error for invalid credentials', async ({ page }) => {
  await page.goto('/login');

  await page.locator('input[type="email"]').fill('wrong@example.com');
  await page.locator('#login-password').fill('wrongpassword123');
  await page.locator('button[type="submit"]').click();

  // Expect an error message to appear in the error div
  // The error container has class bg-semantic-error-bg per LoginPage.tsx
  const errorDiv = page.locator('.bg-semantic-error-bg');
  await expect(errorDiv).toBeVisible({ timeout: 10_000 });
});

// ── Show/hide password toggle ─────────────────────────────────────────────────

test('password visibility toggle works', async ({ page }) => {
  await page.goto('/login');

  const passwordInput = page.locator('#login-password');
  await expect(passwordInput).toHaveAttribute('type', 'password');

  // Click the show-password button (tabIndex=-1 button beside the input)
  const toggleBtn = page.locator('button[tabindex="-1"]');
  await toggleBtn.click();

  await expect(passwordInput).toHaveAttribute('type', 'text');

  // Click again to hide
  await toggleBtn.click();
  await expect(passwordInput).toHaveAttribute('type', 'password');
});

// ── Navigation links on login page ───────────────────────────────────────────

test('forgot password link navigates to /forgot-password', async ({ page }) => {
  await page.goto('/login');

  await page.getByRole('link', { name: /forgot password/i }).click();
  await expect(page).toHaveURL(/\/forgot-password/);
});

test('create account link navigates to /register', async ({ page }) => {
  await page.goto('/login');

  await page.getByRole('link', { name: /create account/i }).click();
  await expect(page).toHaveURL(/\/register/);
});

// ── Logout ────────────────────────────────────────────────────────────────────

test('logout clears auth state and redirects to /login', async ({ page }) => {
  await login(page);

  // Confirm we are authenticated (not on login page)
  await expect(page).not.toHaveURL(/\/login/);

  // Use the helper to clear tokens and navigate
  await logout(page);

  await expect(page).toHaveURL(/\/login/);
});

// ── Protected route redirect ──────────────────────────────────────────────────

test('unauthenticated user accessing /projects is redirected to /login', async ({ page }) => {
  // Ensure no tokens in storage
  await page.goto('/login');
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  // Navigate directly to a protected route
  await page.goto('/projects');
  await expect(page).toHaveURL(/\/login/, { timeout: 8_000 });
});

test('unauthenticated user accessing /boq is redirected to /login', async ({ page }) => {
  await page.goto('/login');
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  await page.goto('/boq');
  await expect(page).toHaveURL(/\/login/, { timeout: 8_000 });
});
