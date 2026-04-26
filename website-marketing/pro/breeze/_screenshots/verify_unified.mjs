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

const eco = await page.locator('.ddc-ecosystem').elementHandle();
if (!eco) { console.log('NOT FOUND'); await browser.close(); process.exit(1); }
await eco.scrollIntoViewIfNeeded();
await page.waitForTimeout(1500);
await eco.screenshot({ path: './ddc-ecosystem-unified.png' });
console.log('captured ddc-ecosystem-unified.png');

await browser.close();
