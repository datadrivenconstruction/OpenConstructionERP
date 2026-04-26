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

const wrap = await page.locator('#voices').elementHandle();
if (!wrap) { console.log('NOT FOUND #voices'); await browser.close(); process.exit(1); }
await wrap.scrollIntoViewIfNeeded();
await page.waitForTimeout(1000);
await wrap.screenshot({ path: './voices_full_live.png' });
console.log('captured voices_full_live.png');

await browser.close();
