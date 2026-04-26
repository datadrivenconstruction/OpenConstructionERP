import { chromium } from '../../../../frontend/node_modules/playwright/index.mjs';

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
const page = await ctx.newPage();
await page.goto('https://openconstructionerp.com/?lang=en', { waitUntil: 'networkidle' });

await page.evaluate(() => {
  document.querySelectorAll('.reveal').forEach(el => {
    el.classList.add('is-visible');
    el.style.opacity = '1';
    el.style.transform = 'none';
  });
  const cb = document.querySelector('.cookie-banner');
  if (cb) cb.style.display = 'none';
});

await page.locator('.ddc-socials').scrollIntoViewIfNeeded();
await page.waitForTimeout(1500);

const box = await page.locator('.ddc-socials').boundingBox();
if (!box) { console.log('NOT FOUND'); await browser.close(); process.exit(1); }
await page.screenshot({
  path: './ddc-socials-only.png',
  clip: { x: 0, y: box.y - 20, width: 1440, height: box.height + 40 }
});
console.log(`captured ddc-socials-only.png — h=${Math.round(box.height)}px`);

await browser.close();
