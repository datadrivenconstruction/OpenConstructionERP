import { test } from '@playwright/test';

test('breeze sections', async ({ page }) => {
  test.setTimeout(180000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('http://localhost:8765/pro/breeze/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(5000);
  // Kill all animations for stable element shots
  await page.addStyleTag({ content: `
    *, *::before, *::after {
      animation: none !important;
      transition: none !important;
    }
  `});
  await page.evaluate(() => {
    document.querySelectorAll('.reveal').forEach((el) => el.classList.add('is-visible'));
    document.querySelectorAll('[data-count]').forEach((el: any) => {
      const target = parseFloat(el.dataset.count || '0');
      const suffix = el.dataset.suffix || '';
      el.innerHTML = (target >= 1000 ? target.toLocaleString('en-US') : target.toString())
        + (suffix ? '<span class="suffix">' + suffix + '</span>' : '');
    });
    document.querySelectorAll('.word > span').forEach((el: any) => {
      el.style.transform = 'translate(0,0)';
      el.style.opacity = '1';
    });
    document.querySelectorAll('#fx-eyebrow,#fx-sub,#fx-ctas,#install-wrap,#fx-meta,#hero-panel').forEach((el: any) => {
      el.style.opacity = '1';
      el.style.transform = 'none';
    });
  });
  await page.waitForTimeout(800);

  const sections = [
    { id: 'problem',   file: 'sec-problem.png' },
    { id: 'numbers',   file: 'sec-numbers.png' },
    { id: 'features',  file: 'sec-features.png' },
    { id: 'tour',      file: 'sec-tour.png' },
    { id: 'boq-demo',  file: 'sec-boq.png' },
    { id: 'compare',   file: 'sec-compare.png' },
    { id: 'stack',     file: 'sec-stack.png' },
    { id: 'voices',    file: 'sec-voices.png' },
    { id: 'community', file: 'sec-community.png' },
    { id: 'pricing',   file: 'sec-pricing.png' },
    { id: 'faq',       file: 'sec-faq.png' },
    { id: 'install',   file: 'sec-final.png' },
  ];

  for (const s of sections) {
    const el = await page.$('#' + s.id);
    if (!el) continue;
    await el.scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    await el.screenshot({ path: '../website-marketing/pro/.preview/' + s.file });
  }
});
