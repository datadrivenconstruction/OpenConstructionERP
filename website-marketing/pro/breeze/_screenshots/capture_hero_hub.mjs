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
await page.waitForTimeout(2500);
await page.screenshot({ path: path.resolve(__dirname, 'hero-hub-t1.png'), clip: { x: 0, y: 0, width: 1440, height: 900 } });
await page.waitForTimeout(800);
await page.screenshot({ path: path.resolve(__dirname, 'hero-hub-t2.png'), clip: { x: 0, y: 0, width: 1440, height: 900 } });
await page.waitForTimeout(800);
await page.screenshot({ path: path.resolve(__dirname, 'hero-hub-t3.png'), clip: { x: 0, y: 0, width: 1440, height: 900 } });
await browser.close();
console.log('done');
