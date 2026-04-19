import { test } from '@playwright/test';

const variants = [
  { name: 'aerial', url: 'http://localhost:8765/pro/aerial/' },
  { name: 'cloud', url: 'http://localhost:8765/pro/cloud/' },
  { name: 'breeze', url: 'http://localhost:8765/pro/breeze/' },
];

for (const v of variants) {
  test(`shot ${v.name}`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    page.on('console', (m) => {
      if (m.type() === 'error') errors.push('CONSOLE: ' + m.text());
    });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(v.url, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(3500);
    await page.screenshot({
      path: `../website-marketing/pro/.preview/${v.name}.png`,
      fullPage: false,
    });
    if (errors.length) console.log(`[${v.name}] ERRORS:`, JSON.stringify(errors));
  });
}
