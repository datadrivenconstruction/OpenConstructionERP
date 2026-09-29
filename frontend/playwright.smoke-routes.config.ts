import { defineConfig, devices } from '@playwright/test';

/**
 * Smoke-every-route: every <Route path> in src/app/App.tsx plus every sidebar
 * entry, opened as the demo admin against the single-server build on :8000.
 * One worker on purpose: the spec resolves seeded ids once in beforeAll and
 * the backend shares the runner's four cores. The app must already be running
 * (no webServer auto-start). Findings land in qa-routes/, folded into a table
 * by scripts/smoke-routes-report.mjs.
 */
export default defineConfig({
  testDir: './tests/e2e',
  testMatch: ['smoke-every-route.spec.ts'],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  reporter: [['list'], ['html', { outputFolder: 'qa-routes/html', open: 'never' }]],
  outputDir: 'qa-routes/test-results',
  use: {
    baseURL: process.env.OE_TEST_BASE_URL ?? 'http://127.0.0.1:8000',
    screenshot: 'only-on-failure',
    video: 'off',
    trace: 'off',
    ignoreHTTPSErrors: true,
    navigationTimeout: 30_000,
    actionTimeout: 10_000,
    viewport: { width: 1440, height: 900 },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
});
