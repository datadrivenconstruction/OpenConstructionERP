/**
 * Phase 5 — responsive sweep.
 *
 * Captures 15 hub routes at 3 viewports: mobile (390×844), tablet (768×1024),
 * desktop (1440×900). Records horizontal-overflow presence + broken layout.
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
const OUT_DIR = path.resolve(__dirname, '..', '..', 'audit', 'screenshots', 'phase5');

const VIEWPORTS: { name: string; w: number; h: number }[] = [
  { name: 'mobile', w: 390, h: 844 },
  { name: 'tablet', w: 768, h: 1024 },
  { name: 'desktop', w: 1440, h: 900 },
];

const ROUTES = [
  '/', '/documents', '/cabinets', '/invoices', '/invoices/new',
  '/accounting', '/banking', '/contacts', '/contracts', '/projects',
  '/tasks', '/workflows', '/compliance', '/anlagen', '/settings',
];

type Entry = {
  route: string;
  viewport: string;
  screenshot: string;
  horizontalOverflow: boolean;
  scrollWidth: number;
  viewportWidth: number;
};

const entries: Entry[] = [];

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
    const payload = {
      state: {
        user: { id: userId, email: 'admin@demo.de', firstName: 'Max', lastName: 'Mueller', role: 'admin', orgId: 'demo', orgName: 'Muster GmbH' },
        tokens: { access, refresh },
        isAuthenticated: true,
      }, version: 0,
    };
    localStorage.setItem('dokufluss-auth', JSON.stringify(payload));
    localStorage.setItem('dokufluss-onboarding-done', 'true');
    localStorage.setItem('dokufluss-tour-completed', 'true');
  }, t);
}

test.describe.serial('Phase 5 — responsive sweep', () => {
  test.setTimeout(1000 * 60 * 30);

  test('15 routes × 3 viewports', async ({ browser }) => {
    const tokens = await apiLogin(BASE);

    for (const vp of VIEWPORTS) {
      const ctx = await browser.newContext({ viewport: { width: vp.w, height: vp.h }, locale: 'de-DE' });
      const page = await ctx.newPage();
      await seed(page, tokens);

      for (const route of ROUTES) {
        await page.goto(route, { waitUntil: 'domcontentloaded' });
        await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
        await page.waitForTimeout(300);

        // Measure horizontal overflow on <body>
        const metrics = await page.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          viewportWidth: window.innerWidth,
        }));
        const overflow = metrics.scrollWidth > metrics.viewportWidth + 4; // 4px slack

        const safeRoute = route.replace(/\//g, '_') || '_root';
        const fname = `${vp.name}-${safeRoute}.png`;
        const rel = path.join(vp.name, fname);
        fs.mkdirSync(path.join(OUT_DIR, vp.name), { recursive: true });
        await page.screenshot({ path: path.join(OUT_DIR, rel), fullPage: false, animations: 'disabled' }).catch(() => {});

        entries.push({
          route, viewport: vp.name, screenshot: rel,
          horizontalOverflow: overflow,
          scrollWidth: metrics.scrollWidth, viewportWidth: metrics.viewportWidth,
        });
      }
      await ctx.close();
    }

    // Report
    const overflowed = entries.filter((e) => e.horizontalOverflow);
    const summary = {
      baseUrl: BASE,
      generatedAt: new Date().toISOString(),
      totalShots: entries.length,
      withHorizontalOverflow: overflowed.length,
      overflowed,
      allEntries: entries,
    };
    fs.mkdirSync(OUT_DIR, { recursive: true });
    fs.writeFileSync(path.join(OUT_DIR, '_responsive-report.json'), JSON.stringify(summary, null, 2), 'utf-8');
    expect(entries.length).toBe(ROUTES.length * VIEWPORTS.length);
  });
});
