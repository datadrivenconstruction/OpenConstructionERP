import { chromium } from '../../../../frontend/node_modules/playwright/index.mjs';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
const page = await ctx.newPage();
await page.goto('https://openconstructionerp.com/pro/breeze/?nocache=' + Date.now(), { waitUntil: 'networkidle' });
// hide cookie banner
await page.evaluate(() => { const cb = document.querySelector('.cookie-banner'); if (cb) cb.style.display = 'none'; });
await page.waitForTimeout(400);

// Crop 1: tight on OCERP hub with GitHub behind
const hub = await page.locator('.hero-hub').boundingBox();
if (hub) {
  await page.screenshot({
    path: './crop-hero-hub.png',
    clip: { x: Math.max(0, hub.x - 140), y: Math.max(0, hub.y - 140), width: 400, height: 400 }
  });
}

// Crop 2: tight on video thumbnail
await page.evaluate(() => document.querySelector('.video-intro')?.scrollIntoView({ behavior: 'instant', block: 'start' }));
await page.waitForTimeout(800);
const vid = await page.locator('.video-intro-frame').boundingBox();
if (vid) {
  await page.screenshot({
    path: './crop-video.png',
    clip: { x: vid.x, y: vid.y, width: vid.width, height: vid.height }
  });
}
console.log('OK');
await ctx.close();
await browser.close();
