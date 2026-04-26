import { chromium } from '../../../../frontend/node_modules/playwright/index.mjs';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
const page = await ctx.newPage();
await page.goto('https://openconstructionerp.com/?lang=de&nocache=' + Date.now(), { waitUntil: 'networkidle' });
const diag = await page.evaluate(() => {
  const card = document.querySelector('.ddc-card');
  return {
    innerHTMLLen: card ? card.innerHTML.length : 0,
    innerHTMLPreview: card ? card.innerHTML.slice(0, 500) : '',
    title: card?.querySelector('.ddc-card-title')?.textContent,
    desc: card?.querySelector('.ddc-card-desc')?.textContent?.slice(0, 80),
  };
});
console.log(JSON.stringify(diag, null, 2));
await ctx.close();
await browser.close();
