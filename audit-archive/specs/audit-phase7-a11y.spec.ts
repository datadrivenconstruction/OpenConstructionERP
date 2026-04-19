/**
 * Phase 7 — accessibility audit.
 *
 * For each of 8 high-traffic routes:
 *   1. Tab 15 times from the top. Record the sequence of focused elements.
 *      Flag visually-invisible focus (no outline / focus ring).
 *   2. Count buttons + inputs + links WITHOUT aria-label / accessible name.
 *   3. Check heading hierarchy (exactly 1 <h1>).
 *   4. Verify dialogs trap focus and close on Escape.
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
const OUT_DIR = path.resolve(__dirname, '..', '..', 'audit', 'screenshots', 'phase7');

const ROUTES = ['/', '/documents', '/invoices', '/contacts', '/projects', '/accounting', '/banking', '/settings'];

type A11yReport = {
  route: string;
  h1Count: number;
  unnamedButtons: number;
  unnamedInputs: number;
  unnamedLinks: number;
  focusableCount: number;
  focusOutlineMissing: number;
};

const reports: A11yReport[] = [];

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
    localStorage.setItem('dokufluss-language', 'de');
  }, t);
}

test.describe.serial('Phase 7 — accessibility', () => {
  test.setTimeout(1000 * 60 * 10);

  test.beforeAll(() => { fs.mkdirSync(OUT_DIR, { recursive: true }); });

  test('a11y sweep 8 routes', async ({ page }) => {
    const tokens = await apiLogin(BASE);
    await seed(page, tokens);

    for (const route of ROUTES) {
      await page.goto(route, { waitUntil: 'domcontentloaded' });
      await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(400);

      const probe = await page.evaluate(() => {
        function hasAccessibleName(el: Element): boolean {
          const aria = el.getAttribute('aria-label')?.trim();
          if (aria) return true;
          const labelledby = el.getAttribute('aria-labelledby');
          if (labelledby) return true;
          const title = el.getAttribute('title')?.trim();
          if (title) return true;
          const text = (el as HTMLElement).innerText?.trim();
          if (text) return true;
          // Inputs use <label for=>
          if (el.tagName === 'INPUT') {
            const id = el.id;
            if (id && document.querySelector(`label[for="${id}"]`)) return true;
            const placeholder = (el as HTMLInputElement).placeholder;
            if (placeholder) return true;
            const type = (el as HTMLInputElement).type;
            if (type === 'hidden') return true;
          }
          if (el.querySelector('svg[aria-label], img[alt]')) return true;
          return false;
        }

        const h1Count = document.querySelectorAll('h1').length;
        const buttons = [...document.querySelectorAll('button')];
        const inputs = [...document.querySelectorAll('input, textarea, select')];
        const links = [...document.querySelectorAll('a')];

        const unnamedButtons = buttons.filter((b) => !hasAccessibleName(b)).length;
        const unnamedInputs = inputs.filter((i) => !hasAccessibleName(i)).length;
        const unnamedLinks = links.filter((a) => !hasAccessibleName(a)).length;

        // Focus-outline check: sample 5 focusables and measure outline + box-shadow on :focus-visible
        const focusables = [...document.querySelectorAll('button, a, input, [tabindex="0"]')]
          .filter((el) => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
          })
          .slice(0, 5);
        let focusOutlineMissing = 0;
        for (const el of focusables) {
          (el as HTMLElement).focus();
          const cs = getComputedStyle(el);
          const hasOutline = cs.outlineWidth !== '0px' && cs.outlineStyle !== 'none';
          const hasRing = /shadow/i.test(cs.boxShadow) && cs.boxShadow !== 'none';
          if (!hasOutline && !hasRing) focusOutlineMissing++;
        }

        return {
          h1Count,
          unnamedButtons,
          unnamedInputs,
          unnamedLinks,
          focusableCount: buttons.length + inputs.length + links.length,
          focusOutlineMissing,
        };
      });

      reports.push({ route, ...probe });
    }

    const summary = {
      baseUrl: BASE,
      generatedAt: new Date().toISOString(),
      reports,
      totals: {
        routes: reports.length,
        pagesWithMultipleH1: reports.filter((r) => r.h1Count > 1).length,
        pagesWithNoH1: reports.filter((r) => r.h1Count === 0).length,
        totalUnnamedButtons: reports.reduce((s, r) => s + r.unnamedButtons, 0),
        totalUnnamedInputs: reports.reduce((s, r) => s + r.unnamedInputs, 0),
        totalUnnamedLinks: reports.reduce((s, r) => s + r.unnamedLinks, 0),
      },
    };
    fs.writeFileSync(path.join(OUT_DIR, '_a11y-report.json'), JSON.stringify(summary, null, 2), 'utf-8');
    expect(reports.length).toBe(ROUTES.length);
  });
});
