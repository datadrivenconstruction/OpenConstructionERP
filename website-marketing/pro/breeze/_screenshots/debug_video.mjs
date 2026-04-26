import { chromium } from '../../../../frontend/node_modules/playwright/index.mjs';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
const page = await ctx.newPage();
await page.goto('https://openconstructionerp.com/pro/breeze/?nocache=' + Date.now(), { waitUntil: 'networkidle' });
await page.evaluate(() => { const cb = document.querySelector('.cookie-banner'); if (cb) cb.style.display = 'none'; });
await page.evaluate(() => document.querySelector('.video-intro-frame')?.scrollIntoView({ behavior: 'instant', block: 'center' }));
await page.waitForTimeout(1500);

const diag = await page.evaluate(() => {
  const img = document.querySelector('.video-intro-thumb');
  const frame = document.querySelector('.video-intro-frame');
  const facade = document.querySelector('.video-intro-facade');
  if (!img) return { error: 'no img' };
  const cs = getComputedStyle(img);
  const fr = frame?.getBoundingClientRect();
  const fcr = facade?.getBoundingClientRect();
  const ir = img.getBoundingClientRect();
  return {
    frame: fr ? {w: Math.round(fr.width), h: Math.round(fr.height), y: Math.round(fr.y)} : null,
    facade: fcr ? {w: Math.round(fcr.width), h: Math.round(fcr.height), y: Math.round(fcr.y)} : null,
    img: {
      complete: img.complete,
      natural: `${img.naturalWidth}x${img.naturalHeight}`,
      rect: {w: Math.round(ir.width), h: Math.round(ir.height), y: Math.round(ir.y)},
      display: cs.display,
      opacity: cs.opacity,
      visibility: cs.visibility,
      zIndex: cs.zIndex,
      position: cs.position,
      inset: cs.inset,
    }
  };
});
console.log(JSON.stringify(diag, null, 2));

// Screenshot visible video area
await page.screenshot({ path: './dbg-video-viewport.png', fullPage: false });
await ctx.close();
await browser.close();
