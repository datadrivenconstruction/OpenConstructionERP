import { defineConfig, devices } from '@playwright/test';

/**
 * playwright.captures.config.ts - module showcase video capture.
 *
 * Records a short, deterministic clip per flagship module against the
 * single-server build on :8000 (what actually ships), for the marketing
 * module showcase and the in-app docs. Chromium only, retina-crisp, single
 * worker (videos must not interleave). The app must already be running; this
 * config does NOT auto-start a webServer (CI boots the backend separately,
 * exactly like e2e-cross-os.yml).
 *
 * Per-module .webm files land in frontend/qa-captures/<slug>.webm. The spec
 * manages its own recording contexts (one per module) so each clip is named;
 * the project-level `video` option is therefore left off here on purpose.
 *
 * Run (against an already-running app on :8000):
 *   npx playwright test --config=playwright.captures.config.ts
 */
export default defineConfig({
  testDir: './tests/e2e',
  testMatch: ['capture-module-videos.spec.ts'],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  // Each module records a multi-second clip plus settle time; give the whole
  // spec generous room since all modules run in a single test body.
  timeout: 15 * 60_000,
  reporter: [['list']],
  outputDir: 'qa-captures/test-results',
  use: {
    baseURL: process.env.OE_TEST_BASE_URL ?? 'http://127.0.0.1:8000',
    // The spec creates its own contexts with recordVideo, so leave the
    // fixture-managed page free of screenshots/video/trace overhead.
    screenshot: 'off',
    video: 'off',
    trace: 'off',
    ignoreHTTPSErrors: true,
    navigationTimeout: 30_000,
    actionTimeout: 15_000,
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 },
    },
  ],
});
