import { defineConfig, devices } from '@playwright/test';

/**
 * playwright.homepage-loops.config.ts - marketing homepage showcase loops.
 *
 * Re-records the named loops used by marketing-site/index.html (demo slider +
 * guided tour) against the single-server build on :8000 (what actually ships).
 * Chromium only, retina-crisp, single worker (videos must not interleave). The
 * app must already be running; this config does NOT auto-start a webServer (CI
 * boots the backend separately, exactly like e2e-cross-os.yml).
 *
 * 16:9 to match the homepage media boxes. Named .webm files land in
 * frontend/qa-loops/<name>.webm (the spec manages its own recording contexts),
 * so the project-level `video` option is left off here on purpose.
 *
 * Run (against an already-running app on :8000):
 *   npx playwright test --config=playwright.homepage-loops.config.ts
 */
export default defineConfig({
  testDir: './tests/e2e',
  testMatch: ['capture-homepage-loops.spec.ts'],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 18 * 60_000,
  reporter: [['list']],
  outputDir: 'qa-loops/test-results',
  use: {
    baseURL: process.env.OE_TEST_BASE_URL ?? 'http://127.0.0.1:8000',
    screenshot: 'off',
    video: 'off',
    trace: 'off',
    ignoreHTTPSErrors: true,
    navigationTimeout: 30_000,
    actionTimeout: 15_000,
    viewport: { width: 1440, height: 810 },
    deviceScaleFactor: 2,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 810 }, deviceScaleFactor: 2 },
    },
  ],
});
