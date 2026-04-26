import { chromium } from '../../../../frontend/node_modules/playwright/index.mjs';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
const page = await ctx.newPage();
await page.goto('https://openconstructionerp.com/?lang=de&nocache=' + Date.now(), { waitUntil: 'networkidle' });
await page.evaluate(() => {
  const cb = document.querySelector('.cookie-banner'); if (cb) cb.style.display = 'none';
  document.querySelectorAll('.reveal').forEach(el => { el.classList.add('is-visible'); el.style.opacity='1'; el.style.transform='none'; });
});
const ddc = await page.locator('#ddc').boundingBox();
console.log('ddc', JSON.stringify(ddc));
if (ddc) {
  await page.evaluate((y) => window.scrollTo(0, y - 60), ddc.y);
  await page.waitForTimeout(2500);
  await page.screenshot({ path: './ddc-section.png', clip: { x: 0, y: 0, width: 1440, height: 900 } });
}
await ctx.close();
await browser.close();
