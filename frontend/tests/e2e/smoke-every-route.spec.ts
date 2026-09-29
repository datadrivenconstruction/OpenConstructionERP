/**
 * Smoke-every-route: open every route the app router declares, as the demo
 * admin on a freshly seeded install, and record what breaks.
 *
 * smoke-all-modules.spec.ts walks a hand-kept list of ~95 global pages. That
 * list drifts from the router and never reaches the project-scoped pages
 * (`/projects/:projectId/*`) or the detail pages behind an id, which is where
 * a page that crashes on real seed data hides. This spec reads the route
 * table straight out of src/app/App.tsx, so a new <Route path> is covered the
 * moment it is declared, fills every parameter from the seeded demo data, and
 * adds whatever the sidebar links to on top.
 *
 * Per route it records: the ErrorBoundary fallback, uncaught page errors,
 * console errors, /api responses >= 400 fired while the page loads, a blank
 * main area, the 404 page, "Project not found" on a seeded project, and a
 * bounce to /login. It then clicks the visible tabs of the page once each and
 * attributes anything new to that tab.
 *
 * Hard failures (the test goes red): crash, page error, 404 page, "Project not
 * found", lost session, blank main, or a 5xx. 4xx responses and console errors
 * are recorded for triage but do not fail the route on their own, because a
 * page may legitimately probe an optional endpoint.
 *
 * Each route writes qa-routes/routes/<slug>.json; scripts/smoke-routes-report
 * .mjs folds them into qa-routes/report.md and report.json.
 *
 * Config: playwright.smoke-routes.config.ts. Workflow: smoke-every-route.yml.
 */
import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const API = process.env.OE_TEST_API_URL ?? 'http://127.0.0.1:8000';
const DEMO_EMAIL = process.env.OE_TEST_DEMO_EMAIL ?? 'demo@openconstructionerp.com';
const OUT = path.join(process.cwd(), 'qa-routes');
const ROUTES_DIR = path.join(OUT, 'routes');
const PARAMS_CACHE = path.join(OUT, 'params.json');
const SESSION_CACHE = path.join(OUT, 'session.json');
// Access tokens live 60 minutes and the sweep runs longer, while demo-login is
// rate limited per client; so one token is shared through a file across worker
// restarts and renewed well before it expires.
const TOKEN_MAX_AGE_MS = 35 * 60_000;
const TAB_BUDGET_MS = 25_000;
const RESIZE_OBSERVER_LOOP = 'ResizeObserver loop completed with undelivered notifications.';
const MAX_TABS = Number(process.env.OE_SMOKE_MAX_TABS ?? 8);

// Routes that are not app pages for a signed-in admin: public magic-link
// landings that need a token we do not have, the auth screens that redirect
// an authenticated user away, the OIDC callback, and the catch-all.
const SKIP = new Set([
  '*',
  '/share/:token',
  '/buyer-portal/:token',
  '/field/:token',
  '/login',
  '/login-next',
  '/register',
  '/forgot-password',
  '/auth/oidc/callback',
]);

/** Every literal `<Route path="...">` in App.tsx, in declaration order. */
function routerPaths(): string[] {
  const src = fs.readFileSync(path.join(process.cwd(), 'src', 'app', 'App.tsx'), 'utf8');
  const seen = new Set<string>();
  for (const m of src.matchAll(/<Route\b[^>]*?\bpath="([^"]+)"/g)) {
    const p = m[1]!;
    if (!SKIP.has(p)) seen.add(p);
  }
  return [...seen];
}

const PATTERNS = routerPaths();

type Params = {
  projects: Array<{ id: string; name: string }>;
  // Keyed by the route pattern; the value is the concrete URL to open.
  resolved: Record<string, string>;
};

let TOKEN = '';
let REFRESH = '';
let TOKEN_AT = 0;

async function ensureToken(): Promise<void> {
  if (TOKEN && Date.now() - TOKEN_AT < TOKEN_MAX_AGE_MS) return;
  if (fs.existsSync(SESSION_CACHE)) {
    const c = JSON.parse(fs.readFileSync(SESSION_CACHE, 'utf8')) as { token: string; refresh: string; at: number };
    if (Date.now() - c.at < TOKEN_MAX_AGE_MS) {
      [TOKEN, REFRESH, TOKEN_AT] = [c.token, c.refresh, c.at];
      return;
    }
  }
  const res = await fetch(`${API}/api/v1/users/auth/demo-login/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: DEMO_EMAIL }),
  });
  if (!res.ok) throw new Error(`demo-login failed: ${res.status} ${await res.text()}`);
  const j: Record<string, string> = await res.json();
  TOKEN = j.access_token || j.access || j.token || '';
  REFRESH = j.refresh_token || j.refresh || '';
  TOKEN_AT = Date.now();
  if (!TOKEN) throw new Error('demo-login returned no token');
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(SESSION_CACHE, JSON.stringify({ token: TOKEN, refresh: REFRESH, at: TOKEN_AT }));
}
let PARAMS: Params = { projects: [], resolved: {} };

async function api<T = unknown>(p: string): Promise<T | null> {
  try {
    const r = await fetch(`${API}/api${p}`, { headers: { Authorization: `Bearer ${TOKEN}` } });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

function items(body: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(body)) return body as Array<Record<string, unknown>>;
  if (body && typeof body === 'object') {
    for (const k of ['items', 'results', 'data', 'models', 'schedules', 'developments', 'claims']) {
      const v = (body as Record<string, unknown>)[k];
      if (Array.isArray(v)) return v as Array<Record<string, unknown>>;
    }
  }
  return [];
}

async function firstId(candidates: string[], field = 'id'): Promise<string | null> {
  for (const c of candidates) {
    const first = items(await api(c))[0];
    const v = first?.[field];
    if (typeof v === 'string' || typeof v === 'number') return String(v);
  }
  return null;
}

function fill(pattern: string, values: Record<string, string>): string | null {
  let missing = false;
  const out = pattern.replace(/:([A-Za-z]+)/g, (_, name: string) => {
    const v = values[name];
    if (!v) missing = true;
    return v ? encodeURIComponent(v) : `:${name}`;
  });
  return missing ? null : out;
}

/** Concrete ids the seed actually holds, from the API first, then from links on list pages. */
async function resolveParams(page: Page): Promise<Params> {
  const projects = items(await api('/v1/projects/')).map((p) => ({ id: String(p.id), name: String(p.name ?? '') }));
  const pid = projects[0]?.id ?? '';
  const q = pid ? `project_id=${pid}` : '';

  // Links harvested from list pages: detail pages are often reached only by a
  // click, and the href is the most honest statement of which id the UI uses.
  const harvested: string[] = [];
  const harvestFrom = [
    '/boq', '/bim', '/assemblies', '/rfi', '/schedule', '/accommodation', '/property-dev',
    '/property-dev/dashboards', '/cases', '/modules', `/projects/${pid}/contracts`, '/contracts',
  ];
  for (const p of harvestFrom) {
    try {
      await page.goto(p, { waitUntil: 'domcontentloaded', timeout: 30_000 });
      await page.waitForLoadState('networkidle', { timeout: 8_000 }).catch(() => undefined);
      const hrefs = await page.$$eval('a[href^="/"]', (as) => as.map((a) => a.getAttribute('href') ?? ''));
      harvested.push(...hrefs);
    } catch {
      /* a list page that does not open is reported by its own test */
    }
  }
  const fromLinks = (re: RegExp): string | null => {
    for (const h of harvested) {
      const m = h.split(/[?#]/)[0]!.match(re);
      if (m?.[1]) return decodeURIComponent(m[1]);
    }
    return null;
  };
  const UUIDISH = '([^/]+)';

  const values: Record<string, string | null> = {
    projectId: pid || null,
    boqId: (await firstId([`/v1/boq/boqs/?${q}`])) ?? fromLinks(new RegExp(`^/boq/${UUIDISH}$`)),
    modelId:
      (await firstId([`/v1/bim_hub/?${q}`, `/v1/bim_hub/models/?${q}`])) ??
      fromLinks(new RegExp(`^/(?:projects/[^/]+/)?bim/${UUIDISH}$`)),
    assemblyId: (await firstId(['/v1/assemblies/'])) ?? fromLinks(new RegExp(`^/assemblies/${UUIDISH}$`)),
    rfiId: (await firstId([`/v1/rfi/?${q}`])) ?? fromLinks(new RegExp(`^/rfi/${UUIDISH}$`)),
    devId: (await firstId(['/v1/property-dev/developments/'])) ?? fromLinks(new RegExp(`^/property-dev/developments/${UUIDISH}/`)),
    // Shipped playbooks are source files; the id is the file stem.
    playbookId:
      fs
        .readdirSync(path.join(process.cwd(), 'src', 'features', 'cases', 'data'))
        .find((f) => f.endsWith('.playbook.ts'))
        ?.replace(/\.playbook\.ts$/, '') ?? fromLinks(new RegExp(`^/cases/${UUIDISH}$`)),
    eacId: fromLinks(new RegExp(`^/eac/blocks/${UUIDISH}$`)),
    moduleKey: fromLinks(new RegExp(`^/modules/(?!developer-guide$)${UUIDISH}$`)),
    key: fromLinks(new RegExp(`^/property-dev/dashboards/${UUIDISH}$`)),
    claimId:
      (pid ? await firstId([`/v1/contracts/progress-claims/?${q}`]) : null) ??
      fromLinks(new RegExp(`^/projects/[^/]+/contracts/claims/${UUIDISH}$`)),
  };
  const scheduleId = (await firstId([`/v1/schedule/schedules/?${q}`])) ?? fromLinks(new RegExp(`^/schedule/${UUIDISH}/cpm$`));
  const accommodationId =
    (await firstId(['/v1/accommodation/'])) ?? fromLinks(new RegExp(`^/accommodation/(?!calendar$)${UUIDISH}$`));

  const resolved: Record<string, string> = {};
  for (const pattern of PATTERNS) {
    if (!pattern.includes(':')) {
      resolved[pattern] = pattern;
      continue;
    }
    const v: Record<string, string> = {};
    for (const [k, val] of Object.entries(values)) if (val) v[k] = val;
    if (pattern.startsWith('/schedule/') && scheduleId) v.id = scheduleId;
    if (pattern.startsWith('/accommodation/') && accommodationId) v.id = accommodationId;
    const url = fill(pattern, v);
    if (url) resolved[pattern] = url;
  }

  // Sidebar entries the router table does not spell out (generated modules,
  // query-string variants). Opened as their own rows.
  try {
    await page.goto('/dashboard', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await page.waitForLoadState('networkidle', { timeout: 8_000 }).catch(() => undefined);
    const nav = await page.$$eval('aside a[href^="/"], nav a[href^="/"]', (as) =>
      as.map((a) => a.getAttribute('href') ?? ''),
    );
    const known = new Set(Object.values(resolved));
    for (const h of nav) {
      // /api/source is the AGPL source download, not a page.
      if (h && !h.startsWith('/api/') && !known.has(h)) {
        resolved[`sidebar:${h}`] = h;
        known.add(h);
      }
    }
  } catch {
    /* the dashboard row reports its own failure */
  }
  return { projects, resolved };
}

async function signIn(page: Page, projectId: string | undefined, projectName: string | undefined) {
  await ensureToken();
  await page.addInitScript(
    ({ token, refresh, proj }) => {
      try {
        localStorage.setItem('oe_access_token', token);
        if (refresh) localStorage.setItem('oe_refresh_token', refresh);
        localStorage.setItem('oe_remember', '1');
        sessionStorage.setItem('oe_access_token', token);
        if (refresh) sessionStorage.setItem('oe_refresh_token', refresh);
        if (proj.id) localStorage.setItem('oe_active_project', JSON.stringify({ id: proj.id, name: proj.name, boqId: null }));
        localStorage.setItem('oe_onboarding_completed', '1');
        localStorage.setItem('oe_welcome_dismissed', '1');
        localStorage.setItem('oe_tour_completed', '1');
      } catch {
        /* storage blocked: the login bounce is then reported */
      }
    },
    { token: TOKEN, refresh: REFRESH, proj: { id: projectId ?? '', name: projectName ?? '' } },
  );
}

test.beforeAll(async ({ browser }) => {
  test.setTimeout(10 * 60_000);
  await ensureToken();

  // A failed test restarts the worker and reruns this hook; the harvest costs
  // a minute, so the first worker's answer is reused.
  if (fs.existsSync(PARAMS_CACHE)) {
    PARAMS = JSON.parse(fs.readFileSync(PARAMS_CACHE, 'utf8')) as Params;
    return;
  }
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const first = items(await api('/v1/projects/'))[0];
  await signIn(page, first ? String(first.id) : undefined, first ? String(first.name ?? '') : undefined);
  PARAMS = await resolveParams(page);
  await ctx.close();
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(PARAMS_CACHE, JSON.stringify(PARAMS, null, 2));
});

type Finding = {
  route: string;
  url: string;
  finalUrl: string;
  status: 'ok' | 'fail' | 'soft' | 'unresolved';
  symptoms: string[];
  crashes: string[];
  pageErrors: string[];
  consoleErrors: string[];
  apiErrors: string[];
  tabs: Array<{ tab: string; symptoms: string[]; details: string[] }>;
  tabsClicked: number;
};

function slugOf(route: string): string {
  return route.replace(/^sidebar:/, 'sb_').replace(/[^A-Za-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'root';
}

async function openAndInspect(page: Page, route: string, url: string): Promise<Finding> {
  // Written first so a route that hangs until the test timeout still has a row.
  record({
    route, url, finalUrl: '', status: 'fail', symptoms: ['timed out before the page settled'],
    crashes: [], pageErrors: [], consoleErrors: [], apiErrors: [], tabs: [], tabsClicked: 0,
  });
  const crashes: string[] = [];
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  const apiErrors: string[] = [];
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const t = m.text().slice(0, 400);
    if (t.includes('[ErrorBoundary] Caught render error')) crashes.push(t);
    else consoleErrors.push(t);
  });
  page.on('pageerror', (e) => {
    if (e.message === RESIZE_OBSERVER_LOOP) return;
    pageErrors.push(String(e.stack ?? e).split('\n').slice(0, 3).join(' | ').slice(0, 400));
  });
  page.on('response', (r) => {
    const u = r.url();
    if (r.status() >= 400 && u.includes('/api/')) {
      apiErrors.push(`${r.status()} ${r.request().method()} ${u.replace(API, '').split('?')[0]}`);
    }
  });

  const symptoms: string[] = [];
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  } catch (e) {
    symptoms.push(`navigation: ${String(e).slice(0, 160)}`);
  }
  await page.waitForLoadState('networkidle', { timeout: 6_000 }).catch(() => undefined);
  await page.waitForTimeout(800);

  const inspect = async (): Promise<string[]> => {
    const s: string[] = [];
    const finalUrl = page.url();
    if (/\/login(\?|$|\/)/.test(finalUrl)) s.push('redirected to /login');
    if ((await page.locator('[data-testid="error-boundary-fallback"]').count()) > 0) s.push('error boundary shown');
    const main = page.locator('main').first();
    const mainText = (await main.innerText({ timeout: 3_000 }).catch(() => '')).trim();
    if (/^Page not found/m.test(mainText) || (await page.getByText('Page not found', { exact: true }).count()) > 0) {
      s.push('404 page');
    }
    if (/Project not found/i.test(mainText)) s.push('"Project not found"');
    if ((await main.count()) > 0) {
      const media = await main.locator('canvas, svg, table, img, iframe, [role="grid"]').count();
      if (mainText.length < 15 && media === 0) s.push('blank main content');
    }
    return s;
  };

  let first = await inspect();
  // A <Navigate> route lands on its target a beat after networkidle, and the
  // target's lazy chunk is still loading when main is first read. Blank is only
  // a finding if it is still blank a few seconds later.
  if (first.includes('blank main content')) {
    await page.waitForTimeout(4_000);
    first = await inspect();
  }
  symptoms.push(...first);
  const beforeTabs = {
    crashes: crashes.length,
    pageErrors: pageErrors.length,
    apiErrors: apiErrors.length,
    consoleErrors: consoleErrors.length,
  };

  const tabs: Finding['tabs'] = [];
  let tabsClicked = 0;
  if (!symptoms.some((s) => s.startsWith('redirected') || s.startsWith('error boundary'))) {
    const tabLoc = page.locator('main [role="tab"]:visible');
    const n = Math.min(await tabLoc.count().catch(() => 0), MAX_TABS);
    const labels: string[] = [];
    for (let i = 0; i < n; i++) labels.push(((await tabLoc.nth(i).innerText().catch(() => '')) || `#${i}`).trim().slice(0, 40));
    const tabsStarted = Date.now();
    for (let i = 0; i < n; i++) {
      if (Date.now() - tabsStarted > TAB_BUDGET_MS) break;
      const mark = { c: crashes.length, p: pageErrors.length, a: apiErrors.length, e: consoleErrors.length };
      const here = page.url();
      try {
        await page.locator('main [role="tab"]:visible').nth(i).click({ timeout: 4_000 });
      } catch {
        continue;
      }
      tabsClicked++;
      await page.waitForLoadState('networkidle', { timeout: 5_000 }).catch(() => undefined);
      await page.waitForTimeout(400);
      const s = (await inspect()).filter((x) => x !== 'blank main content');
      const details = [
        ...crashes.slice(mark.c),
        ...pageErrors.slice(mark.p).map((x) => `pageerror: ${x}`),
        ...apiErrors.slice(mark.a),
        ...consoleErrors.slice(mark.e).map((x) => `console: ${x}`),
      ];
      if (crashes.length > mark.c) s.push('crash');
      if (pageErrors.length > mark.p) s.push('page error');
      if (s.length || details.length) tabs.push({ tab: labels[i]!, symptoms: s, details: details.slice(0, 6) });
      if (s.some((x) => x.startsWith('error boundary') || x.startsWith('redirected'))) break;
      if (page.url() !== here) {
        await page.goto(here, { waitUntil: 'domcontentloaded', timeout: 30_000 }).catch(() => undefined);
        await page.waitForLoadState('networkidle', { timeout: 5_000 }).catch(() => undefined);
      }
    }
  }

  const loadCrashes = crashes.slice(0, beforeTabs.crashes);
  const loadPageErrors = pageErrors.slice(0, beforeTabs.pageErrors);
  const loadApi = [...new Set(apiErrors.slice(0, beforeTabs.apiErrors))];
  const loadConsole = [...new Set(consoleErrors.slice(0, beforeTabs.consoleErrors))].filter(
    // The browser echoes every failed fetch as a console line; the response
    // itself is already in apiErrors with its path.
    (c) => !/^Failed to load resource: the server responded with a status of/.test(c),
  );
  if (loadCrashes.length) symptoms.push('crash');
  if (loadPageErrors.length) symptoms.push('page error');
  if (loadApi.some((a) => /^5\d\d /.test(a))) symptoms.push('api 5xx');

  const hard = symptoms.length > 0 || tabs.some((t) => t.symptoms.length > 0);
  const soft = loadApi.length > 0 || loadConsole.length > 0 || tabs.length > 0;
  return {
    route,
    url,
    finalUrl: page.url().replace(/^https?:\/\/[^/]+/, ''),
    status: hard ? 'fail' : soft ? 'soft' : 'ok',
    symptoms,
    crashes: loadCrashes,
    pageErrors: loadPageErrors,
    consoleErrors: loadConsole.slice(0, 10),
    apiErrors: loadApi.slice(0, 15),
    tabs,
    tabsClicked,
  };
}

function record(f: Finding) {
  fs.mkdirSync(ROUTES_DIR, { recursive: true });
  fs.writeFileSync(path.join(ROUTES_DIR, `${slugOf(f.route)}.json`), JSON.stringify(f, null, 2));
}

// One row per router pattern, plus rows for every seeded project's overview
// (the "Project not found" check), plus the sidebar extras discovered at run
// time. Tests are declared statically, so the sidebar rows share one test.
for (const pattern of PATTERNS) {
  test(`route ${pattern}`, async ({ page }) => {
    const url = PARAMS.resolved[pattern];
    if (!url) {
      record({
        route: pattern, url: '', finalUrl: '', status: 'unresolved', symptoms: ['no seeded id for a parameter'],
        crashes: [], pageErrors: [], consoleErrors: [], apiErrors: [], tabs: [], tabsClicked: 0,
      });
      test.skip(true, 'no seeded id for a parameter');
      return;
    }
    const p0 = PARAMS.projects[0];
    await signIn(page, p0?.id, p0?.name);
    const f = await openAndInspect(page, pattern, url);
    record(f);
    expect(f.symptoms.concat(f.tabs.flatMap((t) => t.symptoms.map((s) => `[tab ${t.tab}] ${s}`))), JSON.stringify(f, null, 2)).toEqual([]);
  });
}

test('every seeded project opens', async ({ page }) => {
  test.setTimeout(30 * 60_000);
  const bad: string[] = [];
  for (const p of PARAMS.projects) {
    await signIn(page, p.id, p.name);
    for (const sub of ['', '/boq', '/dashboards']) {
      const route = `seeded:/projects/${p.name || p.id}${sub}`;
      const f = await openAndInspect(page, route, `/projects/${p.id}${sub}`);
      record(f);
      if (f.symptoms.length) bad.push(`${route}: ${f.symptoms.join(', ')}`);
      page.removeAllListeners();
    }
  }
  expect(bad).toEqual([]);
});

test('every sidebar entry opens', async ({ page }) => {
  test.setTimeout(30 * 60_000);
  const p0 = PARAMS.projects[0];
  await signIn(page, p0?.id, p0?.name);
  const bad: string[] = [];
  for (const [route, url] of Object.entries(PARAMS.resolved)) {
    if (!route.startsWith('sidebar:')) continue;
    // The loop outlives one token; each call renews it when due and re-seeds storage.
    await signIn(page, p0?.id, p0?.name);
    const f = await openAndInspect(page, route, url);
    record(f);
    if (f.symptoms.length) bad.push(`${url}: ${f.symptoms.join(', ')}`);
    page.removeAllListeners();
  }
  expect(bad).toEqual([]);
});
