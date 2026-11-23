/**
 * Playwright configuration for the cold-start browser lane.
 *
 * One spec, one browser, one worker, no `webServer`. The server is the product
 * under test: `scripts/ci/browser_cold_start_lane.py` starts the real CLI
 * against an empty data directory, waits for `/api/health` to answer, and only
 * then runs this configuration with `OE_COLD_START_BASE_URL` pointing at the
 * port it bound. A `webServer` block here would mean Playwright starting
 * something itself, and whatever it started would not be the CLI an installer
 * runs - which is the entire subject of the lane.
 *
 * Retries are off on purpose. A retry re-runs the test against a database that
 * the first attempt already wrote to, so the second attempt of "the first
 * account made through the UI owns the install" would be registering the second
 * account and asserting admin for it. A flake in this lane has to be looked at,
 * not absorbed, because the thing it measures is a first boot that only happens
 * once.
 *
 * Traces, screenshots and video are kept on failure and the driver names the
 * directory in the job log, so a red run can be opened rather than reasoned
 * about from a wall of text.
 */
import { defineConfig, devices } from '@playwright/test';

const BASE_URL = process.env.OE_COLD_START_BASE_URL ?? 'http://127.0.0.1:8765';

export default defineConfig({
  testDir: './e2e',
  testMatch: 'cold-start-first-boot.spec.ts',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  // A ceiling, not a budget: a test that comes near it has already failed the
  // thing the lane measures. What it has to sit above is the sum of the ceilings
  // the spec's own waits can consume, so that the message a reader gets is the
  // step's - "the Support and legal card did not render within 120000ms", with
  // the timings that go with it - rather than a bare "Test timeout exceeded".
  //
  // Nothing else bounds a navigation here. Playwright Test's `navigationTimeout`
  // defaults to 0, meaning no timeout, and `page.goto` takes its default from
  // that, so in this configuration a navigation is bounded only by this number
  // (@playwright/test 1.63's own types say so for both options). That makes this
  // the outer bound on every step in the spec, and the two heaviest tests are
  // what size it: the second test's waits sum to 330s and the last test's to
  // 360s, three of them at COLD_STEP_TIMEOUT_MS. Eight minutes is above both
  // with room for the navigations between them, and the job's own
  // `timeout-minutes: 40` remains the bound on a lane in which everything hangs
  // at once.
  timeout: 480_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  outputDir: 'test-results/cold-start',
  use: {
    baseURL: BASE_URL,
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    ignoreHTTPSErrors: true,
    // A cold install has no session and no stored language; starting from an
    // empty storage state keeps the second run of this lane in one job from
    // inheriting the first.
    storageState: undefined,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
