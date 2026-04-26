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

const ddc = await page.locator('#ddc').boundingBox();
if (!ddc) { console.log('NOT FOUND'); await browser.close(); process.exit(1); }

await page.evaluate((y) => window.scrollTo(0, y - 60), ddc.y);
await page.waitForTimeout(2200);

// Use fullPage so we can sweep the entire section at once.
await page.setViewportSize({ width: 1440, height: Math.min(Math.ceil(ddc.height) + 200, 3500) });
await page.evaluate((y) => window.scrollTo(0, y - 40), ddc.y);
await page.waitForTimeout(1200);
await page.screenshot({ path: './ddc-section-v2.png', fullPage: false });
console.log(`captured ddc-section-v2.png — section height ${Math.round(ddc.height)}px`);

// Crop just the marquee for closer detail.
const marquee = await page.locator('.ddc-trusted').boundingBox();
if (marquee) {
  await page.screenshot({
    path: './ddc-marquee-v2.png',
    clip: { x: 0, y: marquee.y, width: 1440, height: Math.min(marquee.height + 20, 600) }
  });
  console.log(`captured ddc-marquee-v2.png — h=${Math.round(marquee.height)}px`);
}

// Crop just the socials row.
const socials = await page.locator('.ddc-socials').boundingBox();
if (socials) {
  await page.screenshot({
    path: './ddc-socials-v2.png',
    clip: { x: 0, y: socials.y - 10, width: 1440, height: socials.height + 30 }
  });
  console.log(`captured ddc-socials-v2.png — h=${Math.round(socials.height)}px`);
}

await browser.close();
