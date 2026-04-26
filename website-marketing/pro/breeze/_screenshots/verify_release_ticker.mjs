import { chromium } from '../../../../frontend/node_modules/playwright/index.mjs';

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1.5 });
const page = await ctx.newPage();
await page.goto('https://openconstructionerp.com/?lang=en&_=' + Date.now(), { waitUntil: 'networkidle' });
await page.waitForTimeout(800);

await page.evaluate(() => {
  document.querySelectorAll('.reveal').forEach(el => el.classList.add('is-visible'));
  const cb = document.querySelector('.cookie-banner'); if (cb) cb.style.display = 'none';
});

const el = await page.locator('.release-ticker').first().elementHandle();
if (!el) { console.log('NOT FOUND .release-ticker'); await browser.close(); process.exit(1); }
await el.scrollIntoViewIfNeeded();
await page.waitForTimeout(800);
await el.screenshot({ path: './release_ticker_live.png' });
console.log('captured release_ticker_live.png');

await browser.close();
