/**
 * Phase 8 — performance audit.
 *
 * Measures for 10 hub routes: navigation duration, DOMContentLoaded, Load,
 * First-Paint, First-Contentful-Paint, and resource-fetch timings.
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
const OUT_DIR = path.resolve(__dirname, '..', '..', 'audit', 'screenshots', 'phase8');

const ROUTES = ['/', '/documents', '/invoices', '/contacts', '/projects', '/accounting', '/banking', '/tasks', '/compliance', '/settings'];

type PerfEntry = {
  route: string;
  ttfbMs: number;
  domContentLoadedMs: number;
  loadMs: number;
  firstPaintMs: number;
  firstContentfulPaintMs: number;
  resourceCount: number;
  resourceBytes: number;
  slowestResource: { url: string; ms: number } | null;
};

const entries: PerfEntry[] = [];

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
        tokens: { access, refresh }, isAuthenticated: true,
      }, version: 0,
    }));
    localStorage.setItem('dokufluss-onboarding-done', 'true');
    localStorage.setItem('dokufluss-tour-completed', 'true');
  }, t);
}

test.describe.serial('Phase 8 — performance', () => {
  test.setTimeout(1000 * 60 * 10);

  test.beforeAll(() => { fs.mkdirSync(OUT_DIR, { recursive: true }); });

  test('perf metrics 10 routes', async ({ page }) => {
    const tokens = await apiLogin(BASE);
    await seed(page, tokens);

    for (const route of ROUTES) {
      await page.goto(route, { waitUntil: 'load' });
      await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
      await page.waitForTimeout(300);

      const probe = await page.evaluate(() => {
        const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined;
        const paints = performance.getEntriesByType('paint');
        const resources = performance.getEntriesByType('resource') as PerformanceResourceTiming[];

        const fp = paints.find((p) => p.name === 'first-paint');
        const fcp = paints.find((p) => p.name === 'first-contentful-paint');

        const slowest = resources.reduce<PerformanceResourceTiming | null>((acc, r) => {
          if (!acc || r.duration > acc.duration) return r;
          return acc;
        }, null);

        const bytes = resources.reduce((s, r) => s + (r.encodedBodySize || r.transferSize || 0), 0);

        return {
          ttfbMs: nav ? Math.round(nav.responseStart - nav.requestStart) : -1,
          domContentLoadedMs: nav ? Math.round(nav.domContentLoadedEventEnd - nav.fetchStart) : -1,
          loadMs: nav ? Math.round(nav.loadEventEnd - nav.fetchStart) : -1,
          firstPaintMs: fp ? Math.round(fp.startTime) : -1,
          firstContentfulPaintMs: fcp ? Math.round(fcp.startTime) : -1,
          resourceCount: resources.length,
          resourceBytes: bytes,
          slowestResource: slowest
            ? { url: slowest.name.split('?')[0]!.slice(-80), ms: Math.round(slowest.duration) }
            : null,
        };
      });

      entries.push({ route, ...probe });
    }

    // Summarize
    const avg = (k: keyof PerfEntry) =>
      Math.round(entries.reduce((s, e) => s + (typeof e[k] === 'number' ? (e[k] as number) : 0), 0) / entries.length);
    const summary = {
      baseUrl: BASE,
      generatedAt: new Date().toISOString(),
      routes: entries.length,
      avgTtfbMs: avg('ttfbMs'),
      avgDomContentLoadedMs: avg('domContentLoadedMs'),
      avgLoadMs: avg('loadMs'),
      avgFirstContentfulPaintMs: avg('firstContentfulPaintMs'),
      totalResourceBytes: entries.reduce((s, e) => s + e.resourceBytes, 0),
      perRoute: entries,
    };
    fs.writeFileSync(path.join(OUT_DIR, '_perf-report.json'), JSON.stringify(summary, null, 2), 'utf-8');
    expect(entries.length).toBe(ROUTES.length);
  });
});
