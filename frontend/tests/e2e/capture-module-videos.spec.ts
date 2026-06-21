/**
 * capture-module-videos: record a short, deterministic showcase clip for each
 * flagship module of the running app, for the marketing module showcase and the
 * in-app docs.
 *
 * For every curated module we:
 *   - open a fresh browser context that records video to qa-captures/;
 *   - boot it already logged-in as the demo user with a pinned active project
 *     (same approach as smoke-all-modules.spec.ts) so real data is on screen;
 *   - navigate to the route, wait for content to settle, then perform ONE
 *     simple, robust interaction (a gentle scroll, plus a hover on the first
 *     toolbar control or data row if one exists) so the clip shows motion;
 *   - close the context, which flushes the video, then rename the random-hash
 *     file to qa-captures/<slug>.webm.
 *
 * Resilient by design: a module that fails to load is logged and skipped; it
 * never fails the whole run, so one broken route cannot cost us the other clips.
 *
 * Runs against the single-server build on :8000 (what actually ships).
 * Config: playwright.captures.config.ts
 */
import { test, expect, chromium, type Browser, type BrowserContext, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const API = process.env.OE_TEST_API_URL ?? process.env.OE_TEST_BASE_URL ?? 'http://127.0.0.1:8000';
const BASE = process.env.OE_TEST_BASE_URL ?? 'http://127.0.0.1:8000';
const DEMO_EMAIL = process.env.OE_TEST_DEMO_EMAIL ?? 'demo@openconstructionerp.com';

const VIEWPORT = { width: 1440, height: 900 };
// Roughly how long each clip should be. Settle + interaction fill this window.
const CLIP_MS = 6000;

interface Module {
  slug: string;
  path: string;
  label: string;
}

// Curated flagship modules for the showcase. Routes are taken verbatim from
// tests/e2e/smoke-all-modules.spec.ts (the canonical route surface).
const MODULES: Module[] = [
  { slug: 'dashboard', path: '/', label: 'Project dashboard' },
  { slug: 'boq', path: '/boq', label: 'Bill of quantities editor' },
  { slug: 'bim', path: '/bim', label: 'BIM model viewer' },
  { slug: 'dwg-takeoff', path: '/dwg-takeoff', label: 'DWG takeoff' },
  { slug: 'pdf-takeoff', path: '/takeoff', label: 'PDF takeoff' },
  { slug: 'benchmarks', path: '/benchmarks', label: 'Cost benchmarks' },
  { slug: 'methodologies', path: '/methodologies', label: 'Estimating methodology cascade' },
  { slug: 'costmodel-5d', path: '/5d', label: '5D cost model' },
  { slug: 'schedule', path: '/schedule', label: 'Schedule' },
  { slug: 'geo-hub', path: '/geo', label: 'Geo hub' },
  { slug: 'ai-estimator', path: '/ai-estimator', label: 'AI estimator' },
  { slug: 'risks', path: '/risks', label: 'Cost risk analysis' },
];

interface Session {
  token: string;
  refresh: string;
  project: { id: string; name: string } | null;
}

const OUT_DIR = path.join(process.cwd(), 'qa-captures');

function ensureDir(p: string): void {
  fs.mkdirSync(p, { recursive: true });
}

/**
 * Demo-login and pick the first project, mirroring smoke-all-modules.spec.ts.
 * Returns the tokens + a project to pin so content-heavy modules render data.
 */
async function openSession(): Promise<Session> {
  const res = await fetch(`${API}/api/v1/users/auth/demo-login/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: DEMO_EMAIL }),
  });
  if (!res.ok) throw new Error(`demo-login failed: ${res.status} ${await res.text()}`);
  const j: Record<string, string> = await res.json();
  const token = j.access_token || j.access || j.token || '';
  const refresh = j.refresh_token || j.refresh || '';
  if (!token) throw new Error(`demo-login returned no token: ${JSON.stringify(j).slice(0, 200)}`);

  let project: { id: string; name: string } | null = null;
  try {
    const pr = await fetch(`${API}/api/v1/projects/`, { headers: { Authorization: `Bearer ${token}` } });
    const pd = await pr.json();
    const items: Array<{ id: string; name: string }> = Array.isArray(pd) ? pd : (pd.items ?? []);
    if (items.length) project = { id: items[0].id, name: items[0].name };
  } catch {
    /* a missing project list is non-fatal; modules still render their chrome */
  }
  return { token, refresh, project };
}

/** Inject a real demo session + pinned active project before app scripts run. */
async function hydrate(context: BrowserContext, session: Session): Promise<void> {
  await context.addInitScript(
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
        // Quiet onboarding/tour overlays that would clutter the clip.
        localStorage.setItem('oe_onboarding_completed', '1');
        localStorage.setItem('oe_welcome_dismissed', '1');
        localStorage.setItem('oe_tour_completed', '1');
      } catch {
        /* ignore */
      }
    },
    { token: session.token, refresh: session.refresh, proj: session.project },
  );
}

/**
 * One representative, deterministic interaction: a gentle scroll down and back,
 * plus a hover on the first toolbar button or data row if present. No flaky
 * assertions, nothing that depends on a specific module's data shape.
 */
async function performShowcaseGesture(page: Page): Promise<void> {
  // Let async data and lazy chunks settle before we start moving.
  await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
  await page.waitForTimeout(1200);

  // Hover the first meaningful control we can find, if any.
  const hoverTargets = [
    'main button:visible',
    '[role="toolbar"] button:visible',
    '.ag-row:visible',
    '[role="row"]:visible',
    'main a:visible',
  ];
  for (const sel of hoverTargets) {
    const el = page.locator(sel).first();
    if (await el.isVisible({ timeout: 500 }).catch(() => false)) {
      await el.hover({ timeout: 1500 }).catch(() => {});
      break;
    }
  }
  await page.waitForTimeout(600);

  // Gentle scroll down then back up so the clip shows the page content.
  await page.mouse.move(VIEWPORT.width / 2, VIEWPORT.height / 2);
  await page.mouse.wheel(0, 700);
  await page.waitForTimeout(900);
  await page.mouse.wheel(0, -700);
  await page.waitForTimeout(700);
}

/** Capture one module's clip into qa-captures/<slug>.webm. Throws on failure. */
async function captureModule(browser: Browser, session: Session, mod: Module): Promise<void> {
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 2,
    baseURL: BASE,
    ignoreHTTPSErrors: true,
    recordVideo: { dir: OUT_DIR, size: VIEWPORT },
  });
  await hydrate(context, session);

  const page = await context.newPage();
  let video = page.video();
  try {
    await page.goto(mod.path, { waitUntil: 'domcontentloaded', timeout: 30000 });
    const start = Date.now();
    await performShowcaseGesture(page);
    // Pad to a consistent clip length so every module reads at a steady pace.
    const remaining = CLIP_MS - (Date.now() - start);
    if (remaining > 0) await page.waitForTimeout(remaining);
    video = page.video();
  } finally {
    // Closing the context flushes and finalizes the video file.
    await context.close();
  }

  // Rename the random-hash webm to <slug>.webm.
  if (video) {
    const raw = await video.path().catch(() => '');
    if (raw && fs.existsSync(raw)) {
      const dest = path.join(OUT_DIR, `${mod.slug}.webm`);
      try {
        fs.rmSync(dest, { force: true });
      } catch {
        /* ignore */
      }
      fs.renameSync(raw, dest);
      return;
    }
  }
  throw new Error(`no video produced for ${mod.slug}`);
}

test('capture flagship module showcase clips', async () => {
  test.setTimeout(14 * 60_000);
  ensureDir(OUT_DIR);

  const session = await openSession();
  const browser = await chromium.launch();

  const ok: string[] = [];
  const failed: Array<{ slug: string; error: string }> = [];
  try {
    for (const mod of MODULES) {
      try {
        await captureModule(browser, session, mod);
        ok.push(mod.slug);
        // eslint-disable-next-line no-console
        console.log(`captured ${mod.slug} -> qa-captures/${mod.slug}.webm`);
      } catch (e) {
        const error = String(e).slice(0, 300);
        failed.push({ slug: mod.slug, error });
        // eslint-disable-next-line no-console
        console.warn(`skipped ${mod.slug}: ${error}`);
      }
    }
  } finally {
    await browser.close();
  }

  // Write a small manifest so downstream tooling knows what was captured.
  const manifest = {
    generatedAt: new Date().toISOString(),
    baseURL: BASE,
    project: session.project?.name ?? null,
    captured: ok,
    failed,
    modules: MODULES.map((m) => ({ slug: m.slug, path: m.path, label: m.label })),
  };
  fs.writeFileSync(path.join(OUT_DIR, 'captures.json'), JSON.stringify(manifest, null, 2));
  // eslint-disable-next-line no-console
  console.log(`module captures done: ${ok.length} ok, ${failed.length} skipped`);

  // The run is a success as long as we captured at least one clip; individual
  // module failures are recorded in captures.json, not fatal to the harness.
  expect(ok.length, `no module clips were captured at all (base=${BASE})`).toBeGreaterThan(0);
});
