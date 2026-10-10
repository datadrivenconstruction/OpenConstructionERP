// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Long-running session soak: three tabs of one browser stay signed in across
 * many access-token expiries and, optionally, a backend restart.
 *
 * Run it against a backend started with a short access token, so the soak
 * crosses many refresh rotations instead of one:
 *
 *   JWT_EXPIRE_MINUTES=2 (or OE_JWT_EXPIRE_MINUTES=2) on the backend
 *   npx playwright test --config=playwright.stability.config.ts session-longrun
 *
 * Environment:
 *   OE_TEST_BASE_URL         frontend, default http://localhost:5173
 *   OE_TEST_API_URL          backend, default http://localhost:8000
 *   OE_TEST_DEMO_EMAIL / OE_TEST_DEMO_PASSWORD   credentials for /auth/login/
 *   SESSION_SOAK_MINUTES     soak length, default 70
 *   SESSION_SOAK_INTERVAL_S  seconds between rounds, default 20
 *   SESSION_SOAK_ROUTES      comma-separated in-app routes, default "/,/projects"
 *   BACKEND_RESTART_CMD      shell command that restarts the backend; the
 *                            restart phase is skipped when unset
 *   BACKEND_RESTART_WAIT_S   how long to wait for /api/health after it, default 180
 *
 * The backend must keep its JWT secret across the restart (JWT_SECRET set, or
 * a persisted data dir); a backend that boots with a new secret refuses every
 * refresh token, and signing out then is the correct outcome, not a defect.
 */
import { spawn } from 'node:child_process';
import { test, expect, type BrowserContext, type Page } from '@playwright/test';

const API_URL = process.env.OE_TEST_API_URL ?? 'http://localhost:8000';
const EMAIL = process.env.OE_TEST_DEMO_EMAIL ?? 'demo@openconstructionerp.com';
const PASSWORD = process.env.OE_TEST_DEMO_PASSWORD ?? 'OpenEstimate2024!';
const SOAK_MINUTES = Number(process.env.SESSION_SOAK_MINUTES ?? 70);
const INTERVAL_MS = Number(process.env.SESSION_SOAK_INTERVAL_S ?? 20) * 1000;
const ROUTES = (process.env.SESSION_SOAK_ROUTES ?? '/,/projects')
  .split(',')
  .map((r) => r.trim())
  .filter(Boolean);
const RESTART_CMD = process.env.BACKEND_RESTART_CMD?.trim() ?? '';
const RESTART_WAIT_MS = Number(process.env.BACKEND_RESTART_WAIT_S ?? 180) * 1000;
const TAB_COUNT = 3;

interface Tokens {
  access: string;
  refresh: string;
}

function tokenLifetimeSeconds(token: string): number | null {
  try {
    const payload = JSON.parse(Buffer.from(token.split('.')[1] ?? '', 'base64url').toString('utf8')) as {
      exp?: number;
      iat?: number;
    };
    return payload.exp && payload.iat ? payload.exp - payload.iat : null;
  } catch {
    return null;
  }
}

async function login(context: BrowserContext): Promise<Tokens> {
  const res = await context.request.post(`${API_URL}/api/v1/users/auth/login/`, {
    data: { email: EMAIL, password: PASSWORD },
    failOnStatusCode: false,
  });
  if (res.ok()) {
    const body = (await res.json()) as { access_token: string; refresh_token: string };
    return { access: body.access_token, refresh: body.refresh_token };
  }
  const demo = await context.request.post(`${API_URL}/api/v1/users/auth/demo-login/`, {
    data: {},
    failOnStatusCode: false,
  });
  expect(demo.ok(), `login=${res.status()} demo-login=${demo.status()}`).toBeTruthy();
  const body = (await demo.json()) as { access_token: string; refresh_token: string };
  return { access: body.access_token, refresh: body.refresh_token };
}

interface TabLog {
  apiCalls: number;
  refreshOk: number;
  refreshRejected: number;
  loginVisits: string[];
}

/** Record every API response, every refresh verdict and every visit to /login. */
function watch(tab: Page, log: TabLog): void {
  tab.on('response', (res) => {
    const url = res.url();
    if (url.includes('/auth/refresh')) {
      if (res.status() === 401) log.refreshRejected += 1;
      else if (res.ok()) log.refreshOk += 1;
    } else if (url.includes('/api/v1/')) {
      log.apiCalls += 1;
    }
  });
  tab.on('framenavigated', (frame) => {
    if (frame === tab.mainFrame() && new URL(frame.url()).pathname.includes('/login')) {
      log.loginVisits.push(`${new Date().toISOString()} ${frame.url()}`);
    }
  });
}

/** Fail the moment any tab is on, or has passed through, the login page, or has lost its refresh token. */
async function assertSignedIn(tabs: Page[], logs: TabLog[], phase: string): Promise<void> {
  for (const [i, tab] of tabs.entries()) {
    expect(logs[i]!.loginVisits, `${phase}: tab ${i + 1} visited the login page`).toEqual([]);
    expect(logs[i]!.refreshRejected, `${phase}: tab ${i + 1} saw a refused refresh`).toBe(0);
    const path = new URL(tab.url()).pathname;
    expect(path, `${phase}: tab ${i + 1} was sent to the login page`).not.toContain('/login');
    const refresh = await tab.evaluate(
      () => localStorage.getItem('oe_refresh_token') ?? sessionStorage.getItem('oe_refresh_token'),
    );
    expect(refresh, `${phase}: tab ${i + 1} lost its refresh token`).toBeTruthy();
  }
}

/**
 * One round: every tab moves to a route at the same moment, through the
 * router (no reload), so their API calls hit an expired access token together
 * and race for the same refresh. Every fourth round reloads instead, which is
 * the cold-start path of the same race.
 */
async function round(tabs: Page[], n: number): Promise<void> {
  const route = ROUTES[n % ROUTES.length];
  await Promise.all(
    tabs.map(async (tab) => {
      if (n % 4 === 3) {
        await tab.reload({ waitUntil: 'domcontentloaded' });
      } else {
        await tab.evaluate((to) => {
          window.history.pushState({}, '', to);
          window.dispatchEvent(new PopStateEvent('popstate'));
        }, route);
      }
    }),
  );
  // Let the queries and any refresh settle before the verdict.
  await Promise.all(tabs.map((tab) => tab.waitForLoadState('networkidle', { timeout: 30_000 }).catch(() => {})));
}

async function waitForBackend(page: Page, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const res = await page.request.get(`${API_URL}/api/health`, { failOnStatusCode: false }).catch(() => null);
    if (res?.ok()) return;
    await page.waitForTimeout(2000);
  }
  throw new Error(`backend did not come back within ${timeoutMs / 1000}s after BACKEND_RESTART_CMD`);
}

async function soak(tabs: Page[], logs: TabLog[], minutes: number, phase: string): Promise<number> {
  const end = Date.now() + minutes * 60_000;
  let n = 0;
  while (Date.now() < end) {
    await round(tabs, n);
    await assertSignedIn(tabs, logs, `${phase} round ${n + 1}`);
    n += 1;
    await tabs[0]!.waitForTimeout(Math.min(INTERVAL_MS, Math.max(0, end - Date.now())));
  }
  return n;
}

test.describe('session survives a long working day across tabs', () => {
  test('three tabs stay signed in through refresh rotations and a backend restart', async ({ browser }) => {
    test.setTimeout((SOAK_MINUTES + 20) * 60_000 + RESTART_WAIT_MS);
    const context = await browser.newContext();
    const tokens = await login(context);

    const lifetime = tokenLifetimeSeconds(tokens.access);
    test.info().annotations.push({ type: 'access-token-lifetime-s', description: String(lifetime) });
    if (lifetime !== null && lifetime > 5 * 60) {
      test.info().annotations.push({
        type: 'warning',
        description: `access token lives ${lifetime}s; start the backend with JWT_EXPIRE_MINUTES=2 to cross many rotations`,
      });
    }

    await context.addInitScript(() => {
      localStorage.setItem('oe_onboarding_completed', 'true');
      localStorage.setItem('oe_welcome_dismissed', 'true');
      localStorage.setItem('oe_tour_completed', 'true');
    });
    const first = await context.newPage();
    // Seeding needs the origin; the visit to /login before any log exists is not a sign-out.
    await first.goto('/login', { waitUntil: 'domcontentloaded' });
    // Seeded once, not from an init script: an init script would put the
    // original pair back on every reload and hide a lost rotation.
    await first.evaluate(
      ({ t, email }) => {
        localStorage.setItem('oe_access_token', t.access);
        localStorage.setItem('oe_refresh_token', t.refresh);
        localStorage.setItem('oe_remember', '1');
        localStorage.setItem('oe_user_email', email);
      },
      { t: tokens, email: EMAIL },
    );
    await first.goto(ROUTES[0]!, { waitUntil: 'domcontentloaded' });
    const tabs = [first];
    const logs: TabLog[] = [];
    const newLog = (): TabLog => ({ apiCalls: 0, refreshOk: 0, refreshRejected: 0, loginVisits: [] });
    logs.push(newLog());
    watch(first, logs[0]!);
    for (let i = 1; i < TAB_COUNT; i += 1) {
      const tab = await context.newPage();
      logs.push(newLog());
      watch(tab, logs[i]!);
      await tab.goto(ROUTES[i % ROUTES.length]!, { waitUntil: 'domcontentloaded' });
      tabs.push(tab);
    }
    await assertSignedIn(tabs, logs, 'start');

    const rounds = await soak(tabs, logs, SOAK_MINUTES, 'soak');
    const totals = logs.map((l, i) => `tab${i + 1}: api=${l.apiCalls} refresh=${l.refreshOk}`).join(', ');
    test.info().annotations.push({ type: 'soak-rounds', description: `${rounds} (${totals})` });
    // A soak that never called the API, or never crossed an expiry, measured nothing.
    for (const [i, l] of logs.entries()) {
      expect(l.apiCalls, `tab ${i + 1} made no API calls during the soak`).toBeGreaterThan(0);
    }
    if (lifetime !== null && lifetime * 1.5 < SOAK_MINUTES * 60) {
      const refreshes = logs.reduce((sum, l) => sum + l.refreshOk, 0);
      expect(refreshes, 'the soak outlived the access token but no tab refreshed').toBeGreaterThan(0);
    }

    if (!RESTART_CMD) {
      test.info().annotations.push({ type: 'skipped-phase', description: 'restart: BACKEND_RESTART_CMD unset' });
    } else {
      // Spawned, not awaited: rounds keep running while the backend is down or
      // booting, which is the window under test. A refresh that meets a dead
      // or booting server is transient and must not sign anyone out.
      let restartDone = false;
      const restart = spawn(RESTART_CMD, { shell: true, stdio: 'inherit' });
      restart.on('exit', () => {
        restartDone = true;
      });
      const deadline = Date.now() + RESTART_WAIT_MS;
      let n = 0;
      while (Date.now() < deadline) {
        await round(tabs, n);
        await assertSignedIn(tabs, logs, `during restart round ${n + 1}`);
        n += 1;
        const health = await first.request
          .get(`${API_URL}/api/health`, { failOnStatusCode: false, timeout: 5000 })
          .catch(() => null);
        if (restartDone && health?.ok()) break;
        await first.waitForTimeout(3000);
      }
      await waitForBackend(first, RESTART_WAIT_MS);
      await soak(tabs, logs, Math.min(5, Math.max(1, SOAK_MINUTES / 10)), 'after restart');
    }

    await context.close();
  });
});
