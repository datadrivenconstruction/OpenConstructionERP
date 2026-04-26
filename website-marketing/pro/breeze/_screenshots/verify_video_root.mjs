import { chromium } from '../../../../frontend/node_modules/playwright/index.mjs';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
const page = await ctx.newPage();
await page.goto('https://openconstructionerp.com/?lang=de&nocache=' + Date.now(), { waitUntil: 'networkidle' });
await page.evaluate(() => { const cb = document.querySelector('.cookie-banner'); if (cb) cb.style.display = 'none'; });
await page.evaluate(() => document.querySelector('.video-intro-frame')?.scrollIntoView({ behavior: 'instant', block: 'center' }));
await page.waitForTimeout(1200);
const diag = await page.evaluate(() => {
  const img = document.querySelector('.video-intro-thumb');
  return img ? { src: img.src, complete: img.complete, naturalW: img.naturalWidth } : 'no img';
});
console.log(JSON.stringify(diag));
await page.screenshot({ path: './root-video.png', fullPage: false });
await ctx.close();
await browser.close();
