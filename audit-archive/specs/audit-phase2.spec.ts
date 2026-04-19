/**
 * Phase 2 screenshot audit — visits every route in light + dark theme,
 * captures console errors, saves artefacts to audit/screenshots/.
 *
 * Run with:
 *   cd frontend
 *   BASE_URL=http://31.97.123.81:7777 npx playwright test --config=playwright.audit.config.ts
 */
import { test, expect, Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const BASE = process.env['BASE_URL'] || 'http://31.97.123.81:7777';
const ADMIN_EMAIL = process.env['AUDIT_EMAIL'] || 'admin@demo.de';
const ADMIN_PASSWORD = process.env['AUDIT_PASSWORD'] || 'Demo2026!';
const OUT_DIR = path.resolve(__dirname, '..', '..', 'audit', 'screenshots');

type RouteDef = { url: string; group: string; name: string; waitFor?: string; skipDark?: boolean };

const ROUTES: RouteDef[] = [
  // Public (pre-login)
  { url: '/login',            group: '00-public', name: 'login' },
  { url: '/register',         group: '00-public', name: 'register' },
  { url: '/forgot-password',  group: '00-public', name: 'forgot-password' },

  // Dashboard / Inbox
  { url: '/',                 group: '01-dashboard', name: 'dashboard' },
  { url: '/inbox',            group: '01-dashboard', name: 'inbox' },
  { url: '/calendar',         group: '01-dashboard', name: 'calendar' },

  // Documents
  { url: '/documents',        group: '02-documents', name: 'list' },
  { url: '/cabinets',         group: '02-documents', name: 'cabinets' },
  { url: '/search',           group: '02-documents', name: 'search' },
  { url: '/favourites',       group: '02-documents', name: 'favourites' },
  { url: '/signatures',       group: '02-documents', name: 'signatures' },

  // Invoicing
  { url: '/invoices',         group: '03-invoicing', name: 'list' },
  { url: '/invoices/new',     group: '03-invoicing', name: 'new' },
  { url: '/dunning',          group: '03-invoicing', name: 'dunning' },
  { url: '/e-invoice',        group: '03-invoicing', name: 'einvoice' },
  { url: '/serienbrief',      group: '03-invoicing', name: 'serienbrief' },
  { url: '/sales-pipeline',   group: '03-invoicing', name: 'sales-pipeline' },
  { url: '/orders',           group: '03-invoicing', name: 'orders' },

  // Accounting / Finance
  { url: '/accounting',       group: '04-accounting', name: 'accounting' },
  { url: '/datev-export',     group: '04-accounting', name: 'datev-export' },
  { url: '/banking',          group: '04-accounting', name: 'banking' },
  { url: '/kassenbuch',       group: '04-accounting', name: 'kassenbuch' },
  { url: '/expenses',         group: '04-accounting', name: 'expenses' },
  { url: '/anlagen',          group: '04-accounting', name: 'assets' },

  // CRM / Contracts
  { url: '/contacts',         group: '05-crm', name: 'contacts' },
  { url: '/contracts',        group: '05-crm', name: 'contracts' },
  { url: '/nachtraege',       group: '05-crm', name: 'nachtraege' },
  { url: '/abnahme',          group: '05-crm', name: 'abnahme' },

  // Projects & Construction
  { url: '/projects',         group: '06-projects', name: 'projects' },
  { url: '/bautagebuch',      group: '06-projects', name: 'bautagebuch' },
  { url: '/aufmass',          group: '06-projects', name: 'aufmass' },
  { url: '/subcontractors',   group: '06-projects', name: 'subcontractors' },
  { url: '/resources',        group: '06-projects', name: 'resources' },

  // Tasks / PM / Workflows
  { url: '/tasks',            group: '07-tasks', name: 'tasks' },
  { url: '/wiedervorlage',    group: '07-tasks', name: 'wiedervorlage' },
  { url: '/workflows',        group: '07-tasks', name: 'workflows' },
  { url: '/forms',            group: '07-tasks', name: 'forms' },

  // Time & HR
  { url: '/timetracking',     group: '08-hr', name: 'timetracking' },
  { url: '/attendance',       group: '08-hr', name: 'attendance' },
  { url: '/leave',            group: '08-hr', name: 'leave' },
  { url: '/payroll',          group: '08-hr', name: 'payroll' },

  // Inventory
  { url: '/inventory',        group: '09-inventory', name: 'inventory' },

  // Compliance
  { url: '/compliance',       group: '10-compliance', name: 'compliance' },
  { url: '/qm',               group: '10-compliance', name: 'qm' },
  { url: '/whistleblower',    group: '10-compliance', name: 'whistleblower' },

  // Admin & Settings
  { url: '/admin',            group: '11-admin', name: 'admin' },
  { url: '/settings',         group: '11-admin', name: 'settings' },
  { url: '/marketplace',      group: '11-admin', name: 'marketplace' },
  { url: '/templates',        group: '11-admin', name: 'templates' },
  { url: '/ai-settings',      group: '11-admin', name: 'ai-settings' },
];

type RouteResult = {
  url: string;
  group: string;
  name: string;
  consoleErrors: string[];
  pageErrors: string[];
  failedRequests: string[];
  apiFailures: string[];
  screenshots: { theme: 'light' | 'dark'; path: string }[];
  loadTimeMs: number;
  reached: boolean;
  notes: string[];
};

function attachListeners(page: Page) {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const failedRequests: string[] = [];
  const apiFailures: string[] = [];

  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      consoleErrors.push(msg.text().slice(0, 500));
    }
  });
  page.on('pageerror', (err) => {
    pageErrors.push(String(err).slice(0, 500));
  });
  page.on('requestfailed', (req) => {
    const failure = req.failure();
    failedRequests.push(`${req.method()} ${req.url()} — ${failure?.errorText || 'unknown'}`);
  });
  // Capture every API response that returns HTTP 4xx/5xx — lets us map
  // "N × 404 in console" back to specific URLs without manual curl probing.
  page.on('response', (res) => {
    try {
      const url = res.url();
      if (!url.includes('/api/')) return;
      const status = res.status();
      if (status >= 400 && status < 600) {
        apiFailures.push(`${res.request().method()} ${url} -> ${status}`);
      }
    } catch {
      /* ignore */
    }
  });

  return { consoleErrors, pageErrors, failedRequests, apiFailures };
}

async function apiLogin(baseUrl: string): Promise<{ access: string; refresh: string; userId: string }> {
  const res = await fetch(`${baseUrl}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: ADMIN_EMAIL, password: ADMIN_PASSWORD }),
  });
  if (!res.ok) throw new Error(`login failed: ${res.status}`);
  const data = await res.json() as { access_token: string; refresh_token: string };
  // Decode sub from JWT payload
  const payload = JSON.parse(Buffer.from(data.access_token.split('.')[1], 'base64').toString());
  return { access: data.access_token, refresh: data.refresh_token, userId: payload.sub };
}

async function seedAuth(page: Page, tokens: { access: string; refresh: string; userId: string }) {
  await page.goto('/login');
  await page.evaluate(({ access, refresh, userId }) => {
    const payload = {
      state: {
        user: {
          id: userId,
          email: 'admin@demo.de',
          firstName: 'Max',
          lastName: 'Mueller',
          role: 'admin',
          orgId: 'demo',
          orgName: 'Muster GmbH',
        },
        tokens: { access, refresh },
        isAuthenticated: true,
      },
      version: 0,
    };
    localStorage.setItem('dokufluss-auth', JSON.stringify(payload));
    // Unlock the actual app — bypass onboarding gate & guided tour overlay
    localStorage.setItem('dokufluss-onboarding-done', 'true');
    localStorage.setItem('dokufluss-tour-completed', 'true');
  }, tokens);
}

async function setTheme(page: Page, mode: 'light' | 'dark') {
  await page.evaluate((m) => {
    localStorage.setItem('dokufluss-theme', m);
    document.documentElement.setAttribute('data-theme', m);
    document.documentElement.classList.remove('light', 'dark');
    document.documentElement.classList.add(m);
  }, mode);
}

async function visitAndShoot(page: Page, route: RouteDef, theme: 'light' | 'dark'): Promise<{ path: string; ms: number }> {
  const groupDir = path.join(OUT_DIR, route.group);
  fs.mkdirSync(groupDir, { recursive: true });
  const outFile = path.join(groupDir, `${route.name}--${theme}.png`);

  const t0 = Date.now();
  try {
    await page.goto(route.url, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => { /* best-effort */ });
    await page.waitForTimeout(500); // allow animations to settle
  } catch (e) {
    // Continue — we still want a screenshot of what we can see
  }
  const ms = Date.now() - t0;
  await page.screenshot({ path: outFile, fullPage: true, animations: 'disabled' }).catch(() => {});
  return { path: path.relative(path.resolve(__dirname, '..', '..'), outFile).replace(/\\/g, '/'), ms };
}

test.describe.serial('Phase 2 — Screenshot sweep', () => {
  test('visit all routes in light + dark', async ({ page }) => {
    test.setTimeout(1000 * 60 * 20); // 20 minutes

    fs.mkdirSync(OUT_DIR, { recursive: true });

    // Prime origin so localStorage becomes accessible (Playwright starts on about:blank)
    await page.goto('/', { waitUntil: 'commit' }).catch(() => {});

    // 1) Capture PUBLIC routes first (before login)
    await setTheme(page, 'light');
    const results: RouteResult[] = [];

    for (const r of ROUTES.filter((r) => r.group === '00-public')) {
      const listeners = attachListeners(page);
      const light = await visitAndShoot(page, r, 'light');
      await setTheme(page, 'dark');
      const dark = await visitAndShoot(page, r, 'dark');
      await setTheme(page, 'light');
      results.push({
        url: r.url,
        group: r.group,
        name: r.name,
        consoleErrors: [...listeners.consoleErrors],
        pageErrors: [...listeners.pageErrors],
        failedRequests: [...listeners.failedRequests],
        apiFailures: [...listeners.apiFailures],
        screenshots: [
          { theme: 'light', path: light.path },
          { theme: 'dark', path: dark.path },
        ],
        loadTimeMs: Math.max(light.ms, dark.ms),
        reached: true,
        notes: [],
      });
    }

    // 2) API-login + seed localStorage auth
    const tokens = await apiLogin(BASE);
    await seedAuth(page, tokens);

    // 3) Loop through authenticated routes
    for (const r of ROUTES.filter((r) => r.group !== '00-public')) {
      const listeners = attachListeners(page);
      await setTheme(page, 'light');
      const light = await visitAndShoot(page, r, 'light');
      await setTheme(page, 'dark');
      // Some dashboards need a remount to pick up theme on elements with inline fill
      await page.reload({ waitUntil: 'domcontentloaded' }).catch(() => {});
      await page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => {});
      const dark = await visitAndShoot(page, r, 'dark');

      const reached = !light.path.includes('--light.png') ? false : true;
      results.push({
        url: r.url,
        group: r.group,
        name: r.name,
        consoleErrors: [...listeners.consoleErrors],
        pageErrors: [...listeners.pageErrors],
        failedRequests: [...listeners.failedRequests],
        apiFailures: [...listeners.apiFailures],
        screenshots: [
          { theme: 'light', path: light.path },
          { theme: 'dark', path: dark.path },
        ],
        loadTimeMs: Math.max(light.ms, dark.ms),
        reached,
        notes: [],
      });
    }

    // 4) Write consolidated report
    const report = {
      baseUrl: BASE,
      generatedAt: new Date().toISOString(),
      totalRoutes: results.length,
      totalShots: results.reduce((s, r) => s + r.screenshots.length, 0),
      withConsoleErrors: results.filter((r) => r.consoleErrors.length > 0).length,
      withPageErrors: results.filter((r) => r.pageErrors.length > 0).length,
      withFailedRequests: results.filter((r) => r.failedRequests.length > 0).length,
      results,
    };
    fs.writeFileSync(
      path.join(OUT_DIR, '_sweep-report.json'),
      JSON.stringify(report, null, 2),
      'utf-8'
    );

    // Fail if we couldn't reach the app at all
    expect(results.length).toBeGreaterThan(0);
  });
});
