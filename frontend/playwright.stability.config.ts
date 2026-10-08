/**
 * Stability suite: long-running session soak and import/export round trips.
 *
 * These specs run for an hour or more against a live stack, so the default
 * harness (playwright.config.ts) ignores them and only this config selects them.
 *
 * Run: npx playwright test --config=playwright.stability.config.ts
 * Env: OE_TEST_BASE_URL (frontend), OE_TEST_API_URL (backend), and the
 *      SESSION_SOAK_* / BACKEND_RESTART_* knobs documented in session-longrun.spec.ts.
 */
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: ['**/session-longrun.spec.ts', '**/import-export*.spec.ts'],
  testIgnore: ['**/tests/e2e/fixtures/**', '**/tests/e2e/helpers/**', '**/node_modules/**'],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { outputFolder: 'qa-report/stability', open: 'never' }]],
  // The soak sets its own timeout from SESSION_SOAK_MINUTES; this covers the rest.
  timeout: 2 * 60 * 60_000,
  expect: { timeout: 30_000 },
  outputDir: 'test-results-stability',
  use: {
    baseURL: process.env.OE_TEST_BASE_URL ?? 'http://localhost:5173',
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    ignoreHTTPSErrors: true,
    navigationTimeout: 90_000,
    actionTimeout: 30_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
