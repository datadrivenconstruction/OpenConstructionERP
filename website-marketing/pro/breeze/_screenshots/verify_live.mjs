import { chromium } from '../../../../frontend/node_modules/playwright/index.mjs';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
const page = await ctx.newPage();
await page.goto('https://openconstructionerp.com/pro/breeze/?nocache=' + Date.now(), { waitUntil: 'networkidle' });

const hubInfo = await page.evaluate(() => {
  const gh = document.querySelector('.hero-hub-gh');
  const mark = document.querySelector('.hero-hub-gh-mark');
  const inner = document.querySelector('.hero-hub-inner');
  const r = gh?.getBoundingClientRect();
  const ir = inner?.getBoundingClientRect();
  const cs = gh ? getComputedStyle(gh) : null;
  const ms = mark ? getComputedStyle(mark) : null;
  return {
    gh: r ? {w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.x), y: Math.round(r.y)} : null,
    inner: ir ? {w: Math.round(ir.width), h: Math.round(ir.height), x: Math.round(ir.x), y: Math.round(ir.y)} : null,
    ghZ: cs?.zIndex,
    markOpacity: ms?.opacity,
  };
});
console.log('HUB:', JSON.stringify(hubInfo));

const imgInfo = await page.evaluate(() => {
  const img = document.querySelector('.video-intro-thumb');
  if (!img) return { error: 'no img' };
  return {
    src: img.src,
    naturalW: img.naturalWidth,
    naturalH: img.naturalHeight,
    complete: img.complete,
    displayW: Math.round(img.getBoundingClientRect().width),
    displayH: Math.round(img.getBoundingClientRect().height),
  };
});
console.log('IMG:', JSON.stringify(imgInfo));

await page.screenshot({ path: './live-hero.png', clip: { x: 0, y: 0, width: 1440, height: 900 } });
await page.evaluate(() => document.querySelector('.video-intro')?.scrollIntoView({ behavior: 'instant' }));
await page.waitForTimeout(600);
await page.screenshot({ path: './live-video.png', clip: { x: 0, y: 0, width: 1440, height: 900 } });
await ctx.close();
await browser.close();
