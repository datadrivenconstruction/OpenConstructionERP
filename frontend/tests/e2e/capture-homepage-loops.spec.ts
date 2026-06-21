/**
 * capture-homepage-loops: record fresh versions of the marketing homepage
 * showcase loops (the demo slider + guided tour on marketing-site/index.html).
 *
 * The homepage references a fixed set of named loops in assets/loops/. This
 * spec re-records each one against the CURRENT app so the marketing animations
 * always show the shipping UI. Output filenames match the existing loop names
 * exactly (e.g. 06_Build_BOQ_Fast.webm) so the CI step can convert them to
 * <name>.gif and drop them straight into the site in place.
 *
 * Same resilient approach as capture-module-videos.spec.ts: boot already
 * logged-in as the demo user with a pinned project, navigate to the scenario's
 * route, perform ONE deterministic interaction, then flush the video. A
 * scenario that fails to load is logged and skipped, never failing the run.
 *
 * 16:9 framing to match the homepage <img> boxes (2000x1125 slider, 1280x720
 * tour). Runs against the single-server build on :8000 (what actually ships).
 * Config: playwright.homepage-loops.config.ts
 */
import { test, expect, chromium, type Browser, type BrowserContext, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const API = process.env.OE_TEST_API_URL ?? process.env.OE_TEST_BASE_URL ?? 'http://127.0.0.1:8000';
const BASE = process.env.OE_TEST_BASE_URL ?? 'http://127.0.0.1:8000';
const DEMO_EMAIL = process.env.OE_TEST_DEMO_EMAIL ?? 'demo@openconstructionerp.com';

// 16:9 to match the homepage media boxes. deviceScaleFactor 2 keeps it crisp;
// the CI step downscales to a sensible GIF width.
const VIEWPORT = { width: 1440, height: 810 };
const CLIP_MS = 8000;

type Gesture =
  | 'default'
  | 'search'
  | 'bim'
  | 'dwg'
  | 'pdf'
  | 'newproject'
  | 'boqexport'
  | 'onboarding';

interface Scenario {
  /** Output base name - must match the existing assets/loops/<name>.gif. */
  file: string;
  path: string;
  gesture: Gesture;
  /** Onboarding needs the first-run overlay, so it must not be suppressed. */
  showOnboarding?: boolean;
}

// The 12 loops referenced by marketing-site/index.html (demo slider + tour).
const SCENARIOS: Scenario[] = [
  { file: '02_AI_Photo_to_Estimate', path: '/ai-estimator', gesture: 'default' },
  { file: '04_PDF_Takeoff', path: '/takeoff', gesture: 'pdf' },
  { file: '05_Instant_Search', path: '/costs', gesture: 'search' },
  { file: '06_Build_BOQ_Fast', path: '/boq', gesture: 'default' },
  { file: '07_Role_Based_Onboarding', path: '/', gesture: 'onboarding', showOnboarding: true },
  { file: '08_New_Project_Global', path: '/projects', gesture: 'newproject' },
  { file: '09_Bulk_Link_BIM_Group', path: '/bim', gesture: 'bim' },
  { file: '10_DWG_Layers', path: '/dwg-takeoff', gesture: 'dwg' },
  { file: '11_Complete_Estimate_6M', path: '/boq', gesture: 'boqexport' },
  { file: '12_Tasks_Linked_To_BIM', path: '/tasks', gesture: 'default' },
  { file: '13_Data_Explorer_Pivot', path: '/data-explorer', gesture: 'default' },
  { file: '14_Projects_Dashboard', path: '/', gesture: 'default' },
];

interface Session {
  token: string;
  refresh: string;
  project: { id: string; name: string } | null;
}

const OUT_DIR = path.join(process.cwd(), 'qa-loops');

function ensureDir(p: string): void {
  fs.mkdirSync(p, { recursive: true });
}

/** Demo-login and pick the first project, mirroring capture-module-videos. */
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
    /* a missing project list is non-fatal */
  }
  return { token, refresh, project };
}

/** Inject a real demo session + pinned active project before app scripts run. */
async function hydrate(context: BrowserContext, session: Session, suppressOnboarding: boolean): Promise<void> {
  await context.addInitScript(
    ({ token, refresh, proj, suppress }) => {
      try {
        localStorage.setItem('oe_access_token', token);
        if (refresh) localStorage.setItem('oe_refresh_token', refresh);
        localStorage.setItem('oe_remember', '1');
        sessionStorage.setItem('oe_access_token', token);
        if (refresh) sessionStorage.setItem('oe_refresh_token', refresh);
        if (proj) {
          localStorage.setItem('oe_active_project', JSON.stringify({ id: proj.id, name: proj.name, boqId: null }));
        }
        if (suppress) {
          localStorage.setItem('oe_onboarding_completed', '1');
          localStorage.setItem('oe_welcome_dismissed', '1');
          localStorage.setItem('oe_tour_completed', '1');
        }
      } catch {
        /* ignore */
      }
    },
    { token: session.token, refresh: session.refresh, proj: session.project, suppress: suppressOnboarding },
  );
}

async function settle(page: Page): Promise<void> {
  await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
  await page.waitForTimeout(1200);
}

async function hoverFirst(page: Page, selectors: string[]): Promise<void> {
  for (const sel of selectors) {
    const el = page.locator(sel).first();
    if (await el.isVisible({ timeout: 500 }).catch(() => false)) {
      await el.hover({ timeout: 1500 }).catch(() => {});
      return;
    }
  }
}

async function gentleScroll(page: Page): Promise<void> {
  await page.mouse.move(VIEWPORT.width / 2, VIEWPORT.height / 2);
  await page.mouse.wheel(0, 600);
  await page.waitForTimeout(900);
  await page.mouse.wheel(0, -600);
  await page.waitForTimeout(700);
}

/** Type a query into the first search-like input we can find. */
async function gestureSearch(page: Page): Promise<void> {
  const candidates = [
    'input[type="search"]',
    'input[placeholder*="Search" i]',
    'input[placeholder*="search" i]',
    '[role="searchbox"]',
    'main input[type="text"]',
  ];
  for (const sel of candidates) {
    const el = page.locator(sel).first();
    if (await el.isVisible({ timeout: 700 }).catch(() => false)) {
      await el.click({ timeout: 1500 }).catch(() => {});
      await el.type('concrete', { delay: 90 }).catch(() => {});
      await page.waitForTimeout(1600);
      return;
    }
  }
  await gentleScroll(page);
}

/** Orbit the BIM canvas a little so the 3D model reads as interactive. */
async function gestureBim(page: Page): Promise<void> {
  await page.waitForTimeout(2500); // let geometry load
  const canvas = page.locator('canvas').first();
  if (await canvas.isVisible({ timeout: 2000 }).catch(() => false)) {
    const box = await canvas.boundingBox().catch(() => null);
    if (box) {
      const cx = box.x + box.width / 2;
      const cy = box.y + box.height / 2;
      await page.mouse.move(cx, cy);
      await page.mouse.down();
      await page.mouse.move(cx + 140, cy + 40, { steps: 24 });
      await page.mouse.move(cx + 60, cy - 60, { steps: 24 });
      await page.mouse.up();
      await page.waitForTimeout(800);
      return;
    }
  }
  await hoverFirst(page, ['[role="tree"] [role="treeitem"]', 'aside button', 'main button:visible']);
}

async function gestureDwg(page: Page): Promise<void> {
  await page.waitForTimeout(1500);
  await hoverFirst(page, [
    'aside [role="row"]',
    'aside li',
    'aside button:visible',
    '[role="toolbar"] button:visible',
  ]);
  await gentleScroll(page);
}

async function gesturePdf(page: Page): Promise<void> {
  await page.waitForTimeout(1500);
  await hoverFirst(page, ['[role="toolbar"] button:visible', 'main button:visible', 'canvas']);
  await page.waitForTimeout(800);
}

/** Open the "New project" dialog to show the create flow. */
async function gestureNewProject(page: Page): Promise<void> {
  const triggers = [
    'button:has-text("New project")',
    'button:has-text("New Project")',
    'a:has-text("New project")',
    'button:has-text("New")',
  ];
  for (const sel of triggers) {
    const el = page.locator(sel).first();
    if (await el.isVisible({ timeout: 800 }).catch(() => false)) {
      await el.click({ timeout: 2000 }).catch(() => {});
      await page.waitForTimeout(1800);
      return;
    }
  }
  await gentleScroll(page);
}

/** Show the BOQ totals and open the export menu (GAEB / Excel / PDF / JSON). */
async function gestureBoqExport(page: Page): Promise<void> {
  await page.mouse.wheel(0, 1200);
  await page.waitForTimeout(900);
  const triggers = ['button:has-text("Export")', 'button:has-text("export")', '[aria-label*="export" i]'];
  for (const sel of triggers) {
    const el = page.locator(sel).first();
    if (await el.isVisible({ timeout: 800 }).catch(() => false)) {
      await el.click({ timeout: 2000 }).catch(() => {});
      await page.waitForTimeout(1600);
      return;
    }
  }
  await page.mouse.wheel(0, -600);
  await page.waitForTimeout(700);
}

/** First-run overlay: just let it render and step once if a Next button shows. */
async function gestureOnboarding(page: Page): Promise<void> {
  await page.waitForTimeout(1500);
  const next = page.locator('button:has-text("Next"), button:has-text("Continue"), button:has-text("Get started")').first();
  if (await next.isVisible({ timeout: 1500 }).catch(() => false)) {
    await next.click({ timeout: 1500 }).catch(() => {});
    await page.waitForTimeout(1400);
  } else {
    await gentleScroll(page);
  }
}

async function performGesture(page: Page, gesture: Gesture): Promise<void> {
  await settle(page);
  try {
    switch (gesture) {
      case 'search':
        await gestureSearch(page);
        break;
      case 'bim':
        await gestureBim(page);
        break;
      case 'dwg':
        await gestureDwg(page);
        break;
      case 'pdf':
        await gesturePdf(page);
        break;
      case 'newproject':
        await gestureNewProject(page);
        break;
      case 'boqexport':
        await gestureBoqExport(page);
        break;
      case 'onboarding':
        await gestureOnboarding(page);
        break;
      default:
        await hoverFirst(page, ['main button:visible', '.ag-row:visible', '[role="row"]:visible', 'main a:visible']);
        await gentleScroll(page);
    }
  } catch {
    /* a gesture failure must never lose the clip */
  }
}

async function captureScenario(browser: Browser, session: Session, sc: Scenario): Promise<void> {
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 2,
    baseURL: BASE,
    ignoreHTTPSErrors: true,
    recordVideo: { dir: OUT_DIR, size: VIEWPORT },
  });
  await hydrate(context, session, !sc.showOnboarding);

  const page = await context.newPage();
  let video = page.video();
  try {
    await page.goto(sc.path, { waitUntil: 'domcontentloaded', timeout: 30000 });
    const start = Date.now();
    await performGesture(page, sc.gesture);
    const remaining = CLIP_MS - (Date.now() - start);
    if (remaining > 0) await page.waitForTimeout(remaining);
    video = page.video();
  } finally {
    await context.close();
  }

  if (video) {
    const raw = await video.path().catch(() => '');
    if (raw && fs.existsSync(raw)) {
      const dest = path.join(OUT_DIR, `${sc.file}.webm`);
      try {
        fs.rmSync(dest, { force: true });
      } catch {
        /* ignore */
      }
      fs.renameSync(raw, dest);
      return;
    }
  }
  throw new Error(`no video produced for ${sc.file}`);
}

test('capture homepage showcase loops', async () => {
  test.setTimeout(16 * 60_000);
  ensureDir(OUT_DIR);

  const session = await openSession();
  const browser = await chromium.launch();

  const ok: string[] = [];
  const failed: Array<{ file: string; error: string }> = [];
  try {
    for (const sc of SCENARIOS) {
      try {
        await captureScenario(browser, session, sc);
        ok.push(sc.file);
        // eslint-disable-next-line no-console
        console.log(`captured ${sc.file} -> qa-loops/${sc.file}.webm`);
      } catch (e) {
        const error = String(e).slice(0, 300);
        failed.push({ file: sc.file, error });
        // eslint-disable-next-line no-console
        console.warn(`skipped ${sc.file}: ${error}`);
      }
    }
  } finally {
    await browser.close();
  }

  const manifest = {
    generatedAt: new Date().toISOString(),
    baseURL: BASE,
    project: session.project?.name ?? null,
    captured: ok,
    failed,
    scenarios: SCENARIOS.map((s) => ({ file: s.file, path: s.path, gesture: s.gesture })),
  };
  fs.writeFileSync(path.join(OUT_DIR, 'loops.json'), JSON.stringify(manifest, null, 2));
  // eslint-disable-next-line no-console
  console.log(`homepage loops done: ${ok.length} ok, ${failed.length} skipped`);

  expect(ok.length, `no homepage loops were captured at all (base=${BASE})`).toBeGreaterThan(0);
});
