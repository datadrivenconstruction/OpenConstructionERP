import { defineConfig } from '@playwright/test';

const BASE = process.env['BASE_URL'] || 'http://31.97.123.81:7777';

export default defineConfig({
  testDir: './e2e',
  testMatch: /audit-phase[2-9]/,
  timeout: 120000,
  retries: 0,
  workers: 1,
  reporter: [['list'], ['json', { outputFile: '../audit/screenshots/_results.json' }]],
  use: {
    baseURL: BASE,
    screenshot: 'off',
    video: 'off',
    trace: 'off',
    viewport: { width: 1440, height: 900 },
    locale: 'de-DE',
    actionTimeout: 10000,
    navigationTimeout: 30000,
    ignoreHTTPSErrors: true,
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
});
