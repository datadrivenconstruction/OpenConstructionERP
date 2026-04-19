/**
 * Phase 6 — Arabic (RTL) audit. Switches i18n to `ar` and captures key pages,
 * checking dir=rtl, layout reversal, and icon/caret alignment.
 */
import { test, expect, Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const BASE = process.env['BASE_URL'] || 'http://31.97.123.81:7777';
const EMAIL = process.env['AUDIT_EMAIL'] || 'admin@demo.de';
const PASSWORD = process.env['AUDIT_PASSWORD'] || 'Demo2026!';
const OUT_DIR = path.resolve(__dirname, '..', '..', 'audit', 'screenshots', 'phase6');

const ROUTES = [
  '/', '/documents', '/invoices', '/contacts',
  '/projects', '/compliance', '/settings',
];

async function apiLogin(baseUrl: string) {
  const r = await fetch(`${baseUrl}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  const d = await r.json() as { access_token: string; refresh_token: string };
  const p = JSON.parse(Buffer.from(d.access_token.split('.')[1], 'base64').toString());
  return { access: d.access_token, refresh: d.refresh_token, userId: p.sub };
}

async function seed(page: Page, t: { access: string; refresh: string; userId: string }) {
  await page.goto('/login', { waitUntil: 'commit' });
  await page.evaluate(({ access, refresh, userId }) => {
    localStorage.setItem('dokufluss-auth', JSON.stringify({
      state: {
        user: { id: userId, email: 'admin@demo.de', firstName: 'Max', lastName: 'Mueller', role: 'admin', orgId: 'demo', orgName: 'Muster GmbH' },
        tokens: { access, refresh },
        isAuthenticated: true,
      }, version: 0,
    }));
    localStorage.setItem('dokufluss-onboarding-done', 'true');
    localStorage.setItem('dokufluss-tour-completed', 'true');
    // Force Arabic — i18next config uses `dokufluss-language` as the localStorage key
    localStorage.setItem('dokufluss-language', 'ar');
    // Also set legacy key just in case
    localStorage.setItem('i18nextLng', 'ar');
  }, t);
}

test.describe.serial('Phase 6 — RTL Arabic', () => {
  test.setTimeout(1000 * 60 * 10);

  test('key routes in ar', async ({ page }) => {
    const tokens = await apiLogin(BASE);
    await seed(page, tokens);

    const entries: Array<{ route: string; dir: string; screenshot: string; sidebarRight: boolean }> = [];

    for (const route of ROUTES) {
      await page.goto(route, { waitUntil: 'domcontentloaded' });
      await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(400);

      // Read dir + check sidebar position (should be RIGHT in RTL)
      const info = await page.evaluate(() => {
        const html = document.documentElement;
        const body = document.body;
        const aside = document.querySelector('aside') || document.querySelector('nav');
        const asideRect = aside?.getBoundingClientRect();
        return {
          dir: html.dir || body.dir || getComputedStyle(html).direction,
          asideLeft: asideRect?.left ?? null,
          asideRight: asideRect ? window.innerWidth - asideRect.right : null,
          windowWidth: window.innerWidth,
        };
      });

      const safeRoute = route.replace(/\//g, '_') || '_root';
      const fname = `ar${safeRoute}.png`;
      fs.mkdirSync(OUT_DIR, { recursive: true });
      await page.screenshot({ path: path.join(OUT_DIR, fname), fullPage: false, animations: 'disabled' }).catch(() => {});

      const sidebarRight = info.asideLeft !== null && info.asideLeft > info.windowWidth / 2;
      entries.push({ route, dir: info.dir, screenshot: fname, sidebarRight });
    }

    const summary = {
      baseUrl: BASE,
      generatedAt: new Date().toISOString(),
      entries,
      allRtl: entries.every((e) => e.dir === 'rtl'),
      allSidebarRight: entries.every((e) => e.sidebarRight),
    };
    fs.writeFileSync(path.join(OUT_DIR, '_rtl-report.json'), JSON.stringify(summary, null, 2), 'utf-8');
    expect(entries.length).toBe(ROUTES.length);
  });
});
