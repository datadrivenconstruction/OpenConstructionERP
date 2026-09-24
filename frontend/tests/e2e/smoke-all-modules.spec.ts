/**
 * Smoke-all-modules: navigate every user-facing route in a real browser,
 * with a real demo session and a pinned active project, and record for each:
 *   - whether auth held (no redirect to /login)
 *   - whether the page crashed (ErrorBoundary logs a known string; pageerror)
 *   - console errors, failing /api responses (>=400)
 *   - suspected untranslated i18n keys leaked into visible text
 *   - a full-page screenshot (for downstream vision analysis)
 *
 * Hard-fails only on: auth lost, or a React crash. Everything else is captured
 * to qa-smoke/<engine>/<slug>.json + screenshot for triage + vision review.
 *
 * Runs against the single-server build on :8000 (what actually ships).
 * Config: playwright.smoke-all.config.ts
 */
import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const API = process.env.OE_TEST_API_URL ?? 'http://127.0.0.1:8000';
const DEMO_EMAIL = process.env.OE_TEST_DEMO_EMAIL ?? 'demo@openconstructionerp.com';

// Exact text WebKit and Chromium raise as a pageerror; see the handler below.
const RESIZE_OBSERVER_LOOP = 'ResizeObserver loop completed with undelivered notifications.';

interface Route {
  slug: string;
  path: string;
  group: string;
  beta?: boolean;
}

// Comprehensive, non-parametric, user-facing route surface (~95 routes).
const ROUTES: Route[] = [
  // Overview
  { slug: 'dashboard', path: '/', group: 'overview' },
  { slug: 'projects', path: '/projects', group: 'overview' },
  { slug: 'files', path: '/files', group: 'overview' },
  // Takeoff
  { slug: 'quantities', path: '/quantities', group: 'takeoff' },
  { slug: 'pdf-takeoff', path: '/takeoff', group: 'takeoff' },
  { slug: 'dwg-takeoff', path: '/dwg-takeoff', group: 'takeoff' },
  { slug: 'bim', path: '/bim', group: 'takeoff' },
  // Estimating
  { slug: 'boq', path: '/boq', group: 'estimating' },
  { slug: 'ai-estimator', path: '/ai-estimator', group: 'estimating', beta: true },
  { slug: 'ai-estimate', path: '/ai-estimate', group: 'estimating', beta: true },
  { slug: 'match-elements', path: '/match-elements', group: 'estimating', beta: true },
  { slug: 'project-intelligence', path: '/project-intelligence', group: 'estimating' },
  { slug: 'methodologies', path: '/methodologies', group: 'estimating' },
  // Cost data
  { slug: 'costs', path: '/costs', group: 'cost-data' },
  { slug: 'catalog', path: '/catalog', group: 'cost-data' },
  { slug: 'assemblies', path: '/assemblies', group: 'cost-data' },
  { slug: 'benchmarks', path: '/benchmarks', group: 'cost-data' },
  // Reality capture & 3D
  { slug: 'geo-hub', path: '/geo', group: 'reality', beta: true },
  { slug: 'pointcloud', path: '/pointcloud', group: 'reality', beta: true },
  { slug: 'data-explorer', path: '/data-explorer', group: 'reality' },
  // Model coordination
  { slug: 'coordination', path: '/coordination', group: 'coordination' },
  { slug: 'bim-federations', path: '/bim/federations', group: 'coordination' },
  { slug: 'clash', path: '/clash', group: 'coordination' },
  { slug: 'bim-rules', path: '/bim/rules', group: 'coordination' },
  { slug: 'requirements-matrix', path: '/requirements/matrix', group: 'coordination' },
  // Scheduling
  { slug: 'schedule', path: '/schedule', group: 'scheduling' },
  { slug: 'schedule-advanced', path: '/schedule-advanced', group: 'scheduling' },
  { slug: 'takt', path: '/takt', group: 'scheduling' },
  { slug: 'tasks', path: '/tasks', group: 'scheduling' },
  // Cost control & risk
  { slug: 'costmodel-5d', path: '/5d', group: 'cost-control' },
  { slug: 'portfolio-capacity', path: '/portfolio/capacity', group: 'cost-control' },
  { slug: 'portfolio-leveling', path: '/portfolio/leveling', group: 'cost-control' },
  { slug: 'risks', path: '/risks', group: 'cost-control' },
  // Commercial
  { slug: 'crm', path: '/crm', group: 'commercial' },
  { slug: 'contracts', path: '/contracts', group: 'commercial' },
  { slug: 'subcontractors', path: '/subcontractors', group: 'commercial' },
  { slug: 'bid-management', path: '/bid-management', group: 'commercial' },
  { slug: 'tendering', path: '/tendering', group: 'commercial' },
  { slug: 'variations', path: '/variations', group: 'commercial' },
  // Procurement & change
  { slug: 'moc', path: '/moc', group: 'procurement' },
  { slug: 'supplier-catalogs', path: '/supplier-catalogs', group: 'procurement' },
  { slug: 'procurement', path: '/procurement', group: 'procurement' },
  { slug: 'changeorders', path: '/changeorders', group: 'procurement' },
  // Field operations
  { slug: 'daily-diary', path: '/daily-diary', group: 'field' },
  { slug: 'field-reports', path: '/field-reports', group: 'field' },
  { slug: 'service', path: '/service', group: 'field' },
  { slug: 'portal', path: '/portal', group: 'field' },
  // Resources & assets
  { slug: 'equipment', path: '/equipment', group: 'resources' },
  { slug: 'resources', path: '/resources', group: 'resources' },
  { slug: 'payroll', path: '/payroll', group: 'resources' },
  { slug: 'assets', path: '/assets', group: 'resources' },
  // Quality
  { slug: 'validation', path: '/validation', group: 'quality' },
  { slug: 'inspections', path: '/inspections', group: 'quality' },
  { slug: 'ncr', path: '/ncr', group: 'quality' },
  { slug: 'punchlist', path: '/punchlist', group: 'quality' },
  { slug: 'closeout', path: '/closeout', group: 'quality' },
  { slug: 'qms', path: '/qms', group: 'quality' },
  { slug: 'compliance-builder', path: '/compliance/builder', group: 'quality' },
  // Safety & ESG
  { slug: 'safety', path: '/safety', group: 'safety' },
  { slug: 'hse-advanced', path: '/hse-advanced', group: 'safety' },
  { slug: 'carbon', path: '/carbon', group: 'safety' },
  { slug: 'sustainability', path: '/sustainability', group: 'safety' },
  // Communication
  { slug: 'contacts', path: '/contacts', group: 'communication' },
  { slug: 'meetings', path: '/meetings', group: 'communication' },
  { slug: 'rfi', path: '/rfi', group: 'communication' },
  { slug: 'correspondence', path: '/correspondence', group: 'communication' },
  { slug: 'collaboration', path: '/collaboration', group: 'communication' },
  // Documents
  { slug: 'submittals', path: '/submittals', group: 'documents' },
  { slug: 'transmittals', path: '/transmittals', group: 'documents' },
  { slug: 'cde', path: '/cde', group: 'documents' },
  { slug: 'photos', path: '/photos', group: 'documents' },
  { slug: 'markups', path: '/markups', group: 'documents' },
  // Real estate
  { slug: 'property-dev', path: '/property-dev', group: 'real-estate' },
  { slug: 'accommodation', path: '/accommodation', group: 'real-estate' },
  { slug: 'property-dev-dashboards', path: '/property-dev/dashboards', group: 'real-estate' },
  // Finance
  { slug: 'finance', path: '/finance', group: 'finance' },
  { slug: 'analytics', path: '/analytics', group: 'finance' },
  { slug: 'reports', path: '/reports', group: 'finance' },
  { slug: 'reporting', path: '/reporting', group: 'finance' },
  // Controls & BI
  { slug: 'project-controls', path: '/project-controls', group: 'controls' },
  { slug: 'bi-dashboards', path: '/bi-dashboards', group: 'controls' },
  { slug: 'dashboards-snapshots', path: '/dashboards', group: 'controls' },
  // Automation & AI
  { slug: 'ai-agents', path: '/ai-agents', group: 'automation', beta: true },
  { slug: 'advisor', path: '/advisor', group: 'automation' },
  { slug: 'erp-chat', path: '/chat', group: 'automation' },
  { slug: 'pipelines', path: '/pipelines', group: 'automation' },
  // Admin & setup
  { slug: 'settings', path: '/settings', group: 'admin' },
  { slug: 'users', path: '/users', group: 'admin' },
  { slug: 'modules', path: '/modules', group: 'admin' },
  { slug: 'governance', path: '/governance', group: 'admin' },
  { slug: 'integrations', path: '/integrations', group: 'admin' },
  { slug: 'audit-log', path: '/admin/audit-log', group: 'admin' },
  { slug: 'about', path: '/about', group: 'admin' },
  { slug: 'setup-databases', path: '/setup/databases', group: 'admin' },
];

let TOKEN = '';
let REFRESH = '';
let PROJECT: { id: string; name: string } | null = null;

test.beforeAll(async () => {
  const res = await fetch(`${API}/api/v1/users/auth/demo-login/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: DEMO_EMAIL }),
  });
  if (!res.ok) throw new Error(`demo-login failed: ${res.status} ${await res.text()}`);
  const j: Record<string, string> = await res.json();
  TOKEN = j.access_token || j.access || j.token || '';
  REFRESH = j.refresh_token || j.refresh || '';
  if (!TOKEN) throw new Error(`demo-login returned no token: ${JSON.stringify(j).slice(0, 200)}`);

  const pr = await fetch(`${API}/api/v1/projects/`, {
    headers: { Authorization: `Bearer ${TOKEN}` },
  });
  const pd = await pr.json();
  const items: Array<{ id: string; name: string }> = Array.isArray(pd) ? pd : pd.items ?? [];
  const [first] = items;
  if (first) PROJECT = { id: first.id, name: first.name };
});

function ensureDir(p: string) {
  fs.mkdirSync(p, { recursive: true });
}

for (const route of ROUTES) {
  test(`smoke ${route.group}/${route.slug}`, async ({ page }, testInfo) => {
    const engine = testInfo.project.name;
    const consoleErrors: string[] = [];
    const crashes: string[] = [];
    const netErrors: string[] = [];

    page.on('console', (m) => {
      if (m.type() !== 'error') return;
      const t = m.text();
      consoleErrors.push(t.slice(0, 500));
      if (t.includes('[ErrorBoundary] Caught render error')) crashes.push(t.slice(0, 500));
    });
    page.on('pageerror', (e) => {
      // The browser reports a ResizeObserver callback that resized its own
      // target as an uncaught error. Nothing threw and nothing unmounted, so it
      // is not a crash; comprehensive/full-e2e.spec.ts treats it as benign too.
      if (e.message === RESIZE_OBSERVER_LOOP) return;
      crashes.push(`pageerror: ${String(e).slice(0, 500)}`);
    });
    page.on('response', (r) => {
      const u = r.url();
      if (r.status() >= 400 && u.includes('/api/')) netErrors.push(`${r.status()} ${u.replace(API, '')}`);
    });

    // Inject a real demo session + pinned active project before app scripts run.
    await page.addInitScript(
      ({ token, refresh, proj }) => {
        try {
          localStorage.setItem('oe_access_token', token);
          if (refresh) localStorage.setItem('oe_refresh_token', refresh);
          localStorage.setItem('oe_remember', '1');
          sessionStorage.setItem('oe_access_token', token);
          if (refresh) sessionStorage.setItem('oe_refresh_token', refresh);
          if (proj) {
            localStorage.setItem('oe_active_project', JSON.stringify({ id: proj.id, name: proj.name, boqId: null }));
          }
          // Quiet onboarding/tour overlays that would obscure screenshots.
          localStorage.setItem('oe_onboarding_completed', '1');
          localStorage.setItem('oe_welcome_dismissed', '1');
          localStorage.setItem('oe_tour_completed', '1');
        } catch {
          /* ignore */
        }
      },
      { token: TOKEN, refresh: REFRESH, proj: PROJECT },
    );

    let navError = '';
    try {
      await page.goto(route.path, { waitUntil: 'domcontentloaded', timeout: 30000 });
    } catch (e) {
      navError = String(e).slice(0, 300);
    }
    // Settle async data + lazy chunks without waiting on streaming/polling endpoints.
    await page.waitForTimeout(2800);
    try {
      await page.addStyleTag({ content: '*{animation:none!important;transition:none!important;caret-color:transparent!important;}' });
    } catch {
      /* ignore */
    }

    const url = page.url();
    const redirectedToLogin = /\/login(\?|$|\/)/.test(url);

    let bodyText = '';
    try {
      bodyText = await page.locator('body').innerText({ timeout: 5000 });
    } catch {
      /* ignore */
    }
    // i18n keys leak as word.word.word (>=3 dot/underscore segments, no spaces).
    const suspectedKeys = Array.from(
      new Set(
        (bodyText.match(/\b[a-z][a-z0-9]*(?:[._][a-z0-9]+){2,}\b/g) || []).filter(
          (k) => !/\.(png|jpg|svg|json|com|io|org|ts|tsx|js)\b/.test(k) && !/(^|[._])\d/.test(k),
        ),
      ),
    ).slice(0, 40);

    const shotDir = path.join(process.cwd(), 'qa-smoke', engine);
    ensureDir(shotDir);
    const shotPath = path.join(shotDir, `${route.slug}.png`);
    try {
      await page.screenshot({ path: shotPath, fullPage: true, timeout: 20000 });
    } catch {
      try {
        await page.screenshot({ path: shotPath, fullPage: false, timeout: 10000 });
      } catch {
        /* ignore */
      }
    }

    const finding = {
      slug: route.slug,
      path: route.path,
      group: route.group,
      beta: !!route.beta,
      engine,
      url,
      redirectedToLogin,
      crashed: crashes.length > 0,
      navError,
      crashes,
      consoleErrorCount: consoleErrors.length,
      consoleErrors: consoleErrors.slice(0, 25),
      netErrors: Array.from(new Set(netErrors)).slice(0, 25),
      suspectedKeys,
      screenshot: path.relative(process.cwd(), shotPath),
    };
    fs.writeFileSync(path.join(shotDir, `${route.slug}.json`), JSON.stringify(finding, null, 2));
    await testInfo.attach('finding', { body: JSON.stringify(finding, null, 2), contentType: 'application/json' });

    // Hard gate: session must hold and the page must not crash.
    expect(redirectedToLogin, `redirected to /login at ${route.path}`).toBe(false);
    expect(crashes, `React crash at ${route.path}: ${crashes.join(' | ')}`).toEqual([]);
  });
}
