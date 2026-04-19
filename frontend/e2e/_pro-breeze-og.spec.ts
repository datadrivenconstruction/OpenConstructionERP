import { test } from '@playwright/test';

test('generate og:image 1200x630', async ({ page }) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width: 1200, height: 630 });
  await page.goto('http://localhost:8765/pro/breeze/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(5500);
  // Force final state for hero + hide chrome like nav and float widgets
  await page.evaluate(() => {
    document.querySelectorAll('.word > span').forEach((el: any) => {
      el.style.transform = 'translate(0,0)';
      el.style.opacity = '1';
    });
    document.querySelectorAll('#fx-eyebrow,#fx-sub,#fx-ctas,#install-wrap,#fx-meta,#hero-panel').forEach((el: any) => {
      el.style.opacity = '1';
      el.style.transform = 'none';
    });
    // Hide nav, floaters, pager for clean hero shot
    document.querySelectorAll('.nav, .float-cta, .section-pager, .scroll-progress').forEach((el: any) => {
      el.style.display = 'none';
    });
    // Force install-wrap + meta to be off so hero is clean-ish
    // Keep them so the image shows CTAs
  });
  await page.waitForTimeout(500);
  await page.screenshot({
    path: '../website-marketing/pro/shared/media/og-breeze.png',
    fullPage: false,
    clip: { x: 0, y: 0, width: 1200, height: 630 },
  });
});
