import { chromium } from '../../../../frontend/node_modules/playwright/index.mjs';

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1.5 });
const page = await ctx.newPage();
await page.goto('https://openconstructionerp.com/?lang=en&_=' + Date.now(), { waitUntil: 'networkidle' });
await page.waitForTimeout(800);

await page.evaluate(() => {
  document.querySelectorAll('.reveal').forEach(el => el.classList.add('is-visible'));
  document.querySelectorAll('.cb-section').forEach(el => el.classList.add('is-in'));
  const cb = document.querySelector('.cookie-banner'); if (cb) cb.style.display = 'none';
});

const el = await page.locator('#custom').first().elementHandle();
if (!el) { console.log('NOT FOUND #custom'); await browser.close(); process.exit(1); }
await el.scrollIntoViewIfNeeded();
await page.waitForTimeout(700);
await el.screenshot({ path: './custom_stage_live.png' });
console.log('captured custom_stage_live.png');

const badges = await page.$$eval('.cb-badge', els => els.map(e => e.innerText.trim()));
const chips = await page.$$eval('.cb-comp-chip', els => els.map(e => e.innerText.trim().replace(/\s+/g, ' ')));
const legend = await page.$$eval('.cb-legend-step', els => els.map(e => e.innerText.trim().replace(/\s+/g, ' ')));
console.log('badges:', badges);
console.log('legend:', legend);
console.log('compliance:', chips);

await browser.close();
