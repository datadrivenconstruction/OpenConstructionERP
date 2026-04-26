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
await page.locator('#module-lab').scrollIntoViewIfNeeded();
await page.waitForTimeout(2000);
// capture module-lab + first portion of developers section
const labBox = await page.locator('#module-lab').boundingBox();
await page.screenshot({
  path: path.resolve(__dirname, 'mlab-with-neighbours.png'),
  clip: { x: 0, y: labBox.y - 100, width: 1440, height: labBox.height + 400 }
});
await browser.close();
console.log('done');
