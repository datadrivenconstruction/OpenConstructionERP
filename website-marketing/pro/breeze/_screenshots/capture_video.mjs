import { chromium } from '../../../../frontend/node_modules/playwright/index.mjs';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pagePath = path.resolve(__dirname, '..', 'index.html');
const url = 'file:///' + pagePath.replace(/\\/g, '/');

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const page = await ctx.newPage();
await page.goto(url, { waitUntil: 'networkidle' });
await page.evaluate(() => { const cb = document.querySelector('.cookie-banner'); if (cb) cb.style.display = 'none'; });
await page.locator('#watch').scrollIntoViewIfNeeded();
await page.waitForTimeout(2000);
const box = await page.locator('#watch').boundingBox();
if (box) {
  await page.screenshot({ path: path.resolve(__dirname, 'video-desktop.png'), clip: { x: 0, y: box.y, width: 1440, height: Math.min(box.height + 40, 900) } });
  console.log(`desktop: ${Math.round(box.height)}px`);
}
await browser.close();
