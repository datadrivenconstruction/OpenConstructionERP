import { chromium } from '../../../../frontend/node_modules/playwright/index.mjs';

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1.5 });
const page = await ctx.newPage();
await page.goto('https://openconstructionerp.com/?lang=en&_=' + Date.now(), { waitUntil: 'networkidle' });
await page.waitForTimeout(1200);

await page.evaluate(() => {
  document.querySelectorAll('.reveal').forEach(el => el.classList.add('is-visible'));
  const cb = document.querySelector('.cookie-banner'); if (cb) cb.style.display = 'none';
});

const el = await page.locator('#voices').first().elementHandle();
if (!el) { console.log('NOT FOUND #voices'); await browser.close(); process.exit(1); }
await el.scrollIntoViewIfNeeded();
await page.waitForTimeout(600);
await el.screenshot({ path: './sidebar_voices_live.png' });
console.log('captured sidebar_voices_live.png');

const cards = await page.$$eval('.voices-aside .voices-ref-card', els => els.length);
const groups = await page.$$eval('.voices-aside-group', els => els.length);
const anchors = await page.$$eval('.voices-aside [id^="voices-ref-"]', els => els.map(e => e.id));
console.log('cards:', cards, 'groups:', groups, 'anchors:', anchors);

await browser.close();
