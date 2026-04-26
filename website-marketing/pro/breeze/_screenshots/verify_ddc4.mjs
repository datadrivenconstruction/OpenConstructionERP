import { chromium } from '../../../../frontend/node_modules/playwright/index.mjs';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
const page = await ctx.newPage();
await page.goto('https://openconstructionerp.com/?lang=de&nocache=' + Date.now(), { waitUntil: 'networkidle' });
await page.evaluate(() => { const cb = document.querySelector('.cookie-banner'); if (cb) cb.style.display = 'none'; });
const diag = await page.evaluate(() => {
  const cards = document.querySelectorAll('.ddc-card');
  return Array.from(cards).slice(0, 3).map(c => {
    const cs = getComputedStyle(c);
    const r = c.getBoundingClientRect();
    return { display: cs.display, opacity: cs.opacity, visibility: cs.visibility, h: Math.round(r.height), w: Math.round(r.width), text: c.textContent.slice(0, 40).replace(/\s+/g, ' ') };
  });
});
console.log(JSON.stringify(diag, null, 2));
await ctx.close();
await browser.close();
