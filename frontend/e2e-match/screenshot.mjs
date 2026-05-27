// Standalone Playwright runner — no test framework. Captures screenshots
// of /match-elements (v2.9.32) end-to-end against the running dev servers.

import { chromium } from 'playwright';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const __dirname_esm = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(__dirname_esm, '../../qa-tests/_match-elements-2026-05-07');
fs.mkdirSync(OUT, { recursive: true });

const FRONTEND = 'http://localhost:5180';
const BACKEND = 'http://localhost:8000';
const USER = { email: 'v19-e2e@openestimate.com', password: 'OpenEstimate2024!' };

async function login(_request) {
  let res = await fetch(`${BACKEND}/api/v1/users/auth/login/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: USER.email, password: USER.password }),
  });
  if (!res.ok) {
    const reg = await fetch(`${BACKEND}/api/v1/users/auth/register/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(USER),
    });
    console.log('register status:', reg.status);
    res = await fetch(`${BACKEND}/api/v1/users/auth/login/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: USER.email, password: USER.password }),
    });
  }
  if (!res.ok) {
    throw new Error(`login failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

(async () => {
  const tokens = await login();
  const access = tokens.access_token;
  const refresh = tokens.refresh_token ?? access;
  console.log('auth tokens acquired');

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  // Hydrate localStorage on the frontend origin
  await page.goto(`${FRONTEND}/about`);
  await page.evaluate(
    ({ access, refresh, email }) => {
      localStorage.setItem('oe_access_token', access);
      localStorage.setItem('oe_refresh_token', refresh);
      localStorage.setItem('oe_user_email', email);
      // Suppress the update-available modal — set dismissed-version pin to a far-future tag
      localStorage.setItem('oe_update_dismissed_version', '99.99.99');
      // Skip onboarding tour
      localStorage.setItem('oe_onboarding_complete', '1');
    },
    { access, refresh, email: USER.email },
  );

  async function dismissUpdateModal() {
    const got = page.locator('button:has-text("Got it")').first();
    if (await got.isVisible().catch(() => false)) {
      await got.click().catch(() => null);
      await page.waitForTimeout(300);
    }
  }

  // 1. Sidebar
  await page.goto(`${FRONTEND}/`);
  await page.waitForLoadState('networkidle').catch(() => null);
  await page.waitForTimeout(800);
  await dismissUpdateModal();
  await page.screenshot({ path: path.join(OUT, '01-sidebar-with-match-elements.png'), fullPage: false });
  console.log('1/7 sidebar captured');

  // 2. Page itself
  await page.goto(`${FRONTEND}/match-elements`);
  await page.waitForLoadState('networkidle').catch(() => null);
  await page.waitForTimeout(2500);
  await dismissUpdateModal();
  await page.screenshot({ path: path.join(OUT, '02-page-loaded.png'), fullPage: true });
  console.log('2/7 page captured');

  // 3. Action bar (top crop)
  await page.screenshot({
    path: path.join(OUT, '03-action-bar.png'),
    clip: { x: 0, y: 0, width: 1440, height: 320 },
  });
  console.log('3/7 action bar captured');

  // 4. Templates panel
  const lib = page.locator('button:has-text("Library")').first();
  if (await lib.isVisible().catch(() => false)) {
    await lib.click();
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(OUT, '04-templates-panel.png'), fullPage: false });
    console.log('4/7 templates panel captured');
    // Close
    await page.keyboard.press('Escape');
    const backdrop = page.locator('div.fixed.inset-0.bg-black\\/30').first();
    if (await backdrop.isVisible().catch(() => false)) {
      await backdrop.click({ position: { x: 10, y: 10 } }).catch(() => null);
    }
    await page.waitForTimeout(400);
  } else {
    console.log('4/7 Library button not visible — skipped');
  }

  // 5. Detail panel (if a group exists)
  const detail = page.locator('button:has-text("Detail")').first();
  if (await detail.isVisible().catch(() => false)) {
    await detail.click();
    await page.waitForTimeout(1500);
    await dismissUpdateModal();
    await page.screenshot({ path: path.join(OUT, '05-detail-panel.png'), fullPage: false });
    console.log('5/7 detail panel captured');

    // No-match modal
    const noMatch = page.locator('button:has-text("No match")').first();
    if (await noMatch.isVisible().catch(() => false)) {
      await noMatch.click();
      await page.waitForTimeout(700);
      await page.screenshot({ path: path.join(OUT, '06-no-match-modal.png'), fullPage: false });
      console.log('6/7 no-match modal captured');
    }
  } else {
    await page.screenshot({ path: path.join(OUT, '05-empty-state.png'), fullPage: true });
    console.log('5/7 empty state captured (no BIM data on this user)');
  }

  // 7. API smoke
  const t = await fetch(`${BACKEND}/api/v1/match_elements/templates`, {
    headers: { Authorization: `Bearer ${access}` },
  });
  console.log('templates HTTP', t.status);

  // Final overview
  await page.goto(`${FRONTEND}/match-elements`);
  await page.waitForLoadState('networkidle').catch(() => null);
  await page.waitForTimeout(800);
  await dismissUpdateModal();
  await page.screenshot({ path: path.join(OUT, '07-final-overview.png'), fullPage: true });
  console.log('7/7 final overview captured');

  await browser.close();
  console.log('\nDONE — screenshots in', OUT);
})().catch((e) => {
  console.error('SPEC ERROR:', e);
  process.exit(1);
});
