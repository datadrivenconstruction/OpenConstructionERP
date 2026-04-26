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

// elementHandle screenshots avoid coordinate confusion entirely.
const wrap = await page.evaluateHandle(() => {
  const head = document.querySelector('.ddc-gh-head');
  const grid = document.querySelector('.ddc-gh-grid');
  if (!head || !grid) return null;
  const w = document.createElement('div');
  w.style.cssText = 'position:absolute;left:0;width:100%;background:transparent;';
  // Wrap by repositioning markers — simpler: just take grid screenshot, then head separately and combine? No — capture parent.
  return grid.parentElement;
});
const handle = wrap.asElement();
if (!handle) { console.log('NOT FOUND'); await browser.close(); process.exit(1); }
await handle.scrollIntoViewIfNeeded();
await page.waitForTimeout(800);
await handle.screenshot({ path: './ddc-gh-grid.png' });
console.log('captured ddc-gh-grid.png via elementHandle');

await browser.close();
