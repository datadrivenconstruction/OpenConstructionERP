import { chromium } from '../../../../frontend/node_modules/playwright/index.mjs';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
const page = await ctx.newPage();
await page.goto('https://openconstructionerp.com/pro/breeze/?nocache=' + Date.now(), { waitUntil: 'networkidle' });
await page.evaluate(() => { const cb = document.querySelector('.cookie-banner'); if (cb) cb.style.display = 'none'; });
await page.evaluate(() => document.querySelector('.ml-stage')?.scrollIntoView({ behavior: 'instant', block: 'center' }));
await page.waitForTimeout(1500);

const diag = await page.evaluate(() => {
  const stage = document.querySelector('.ml-stage');
  const rail = document.querySelector('.ml-rail');
  const cards = document.querySelectorAll('.ml-card');
  const slot = document.querySelector('.ml-slot');
  const term = document.querySelector('.ml-terminal');
  const sr = stage?.getBoundingClientRect();
  const rr = rail?.getBoundingClientRect();
  return {
    stageFound: !!stage,
    stageRect: sr ? {w: Math.round(sr.width), h: Math.round(sr.height), y: Math.round(sr.y)} : null,
    railRect: rr ? {w: Math.round(rr.width), h: Math.round(rr.height)} : null,
    cards: cards.length,
    slotFound: !!slot,
    terminalFound: !!term,
    stageDisplay: stage ? getComputedStyle(stage).display : 'N/A',
    stageVisibility: stage ? getComputedStyle(stage).visibility : 'N/A',
  };
});
console.log(JSON.stringify(diag, null, 2));

await page.screenshot({ path: './ml-stage-live.png', fullPage: false });
await ctx.close();
await browser.close();
