import { chromium } from '../../../../frontend/node_modules/playwright/index.mjs';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pagePath = path.resolve(__dirname, '..', 'index.html');
const url = 'file:///' + pagePath.replace(/\\/g, '/');

const viewports = [
  { name: 'desktop', w: 1440, h: 900 },
  { name: 'ipad',    w: 820,  h: 1180 },
  { name: 'iphone',  w: 390,  h: 844 },
];

const browser = await chromium.launch();
for (const v of viewports) {
  const ctx = await browser.newContext({ viewport: { width: v.w, height: v.h }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.evaluate(() => {
    const cb = document.querySelector('.cookie-banner');
    if (cb) cb.style.display = 'none';
  });
  const loc = page.locator('#modules');
  await loc.scrollIntoViewIfNeeded();
  await page.waitForTimeout(3200);
  const box = await loc.boundingBox();
  if (box) {
    await page.screenshot({
      path: path.resolve(__dirname, `mlab-${v.name}.png`),
      clip: { x: 0, y: box.y, width: v.w, height: Math.min(box.height + 20, 900) }
    });
    console.log(`${v.name}: ${Math.round(box.height)}px`);
  } else {
    console.log(`${v.name}: NOT FOUND`);
  }
  await ctx.close();
}
await browser.close();
