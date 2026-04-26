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

const sec = await page.locator('#ddc').elementHandle();
if (!sec) { console.log('NOT FOUND #ddc'); await browser.close(); process.exit(1); }
await sec.scrollIntoViewIfNeeded();
await page.waitForTimeout(1500);
const box = await sec.boundingBox();
// Capture only top portion of DDC section (head + founder note + sidebar)
await page.screenshot({ path: './ddc_top_live.png', clip: { x: 0, y: box.y, width: 1440, height: Math.min(1300, box.height) } });
console.log('captured ddc_top_live.png');

await browser.close();
