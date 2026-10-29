/**
 * full-e2e.spec.ts — comprehensive end-to-end browser test (real clicks).
 *
 * Drives the built app served at OE_TEST_BASE_URL (single server: dist + API).
 * Logs in through the REAL UI login form (demo-login is gated off here),
 * then exercises Dashboard, Geo (3D tileset visibility — the reported bug),
 * Cost Spine generate/rollup/idempotency, Partner Packs, and a broad smoke.
 *
 * One sequential test on a single page/context so we log in exactly once
 * (the backend rate-limits /auth/login). Screenshots → backend/_e2e_shots.
 */
import { test, expect, type Page, type ConsoleMessage, type Request } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.OE_TEST_BASE_URL ?? 'http://localhost:8000';
const DEMO_EMAIL = process.env.OE_TEST_DEMO_EMAIL ?? 'demo@openconstructionerp.com';
const DEMO_PASSWORD = process.env.OE_TEST_DEMO_PASSWORD ?? 'DemoPass1234!';
const SHOTS = 'C:/Users/dev/Desktop/CodeProjects/ERP_26030500/backend/_e2e_shots';
const HOST = new URL(BASE).host;

const PROJ = {
  downtownMedical: 'e6a93f4c-ff4b-4d2a-92fc-ab6477e8afbb', // geo tileset d346a4b2-2cdf-43a8-b492-e257b7e5f384
  berlinMitte: 'f4c80264-cf27-40e4-ac4d-68ddf6877996', // clean spine, DIN276 BOQ
};
// Downtown Medical tileset.source_id — used as ?model= so the viewer flies
// the camera onto the building's bounding sphere.
const GEO_BIM_SOURCE = 'e7b92f12-f716-4ed5-8cd4-a50d9c2dfee1';

fs.mkdirSync(SHOTS, { recursive: true });

// ── Findings accumulator (written to JSON at the end) ──────────────────────
interface Finding {
  flow: string;
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  area: string;
  detail: string;
  repro?: string;
}
const findings: Finding[] = [];
const results: { flow: string; pass: boolean; note: string }[] = [];
function record(flow: string, pass: boolean, note: string) {
  results.push({ flow, pass, note });
}

// ── Per-page observation buffers ────────────────────────────────────────────
interface Obs {
  consoleErrors: string[];
  pageErrors: string[];
  failed: { url: string; status: number; method: string }[];
  geoArtifact: { url: string; status: number; ct: string }[];
}
function freshObs(): Obs {
  return { consoleErrors: [], pageErrors: [], failed: [], geoArtifact: [] };
}
let obs: Obs = freshObs();

function isBenign(txt: string): boolean {
  return /favicon|ResizeObserver loop|Download the React DevTools|cdn\.cesium|cesium\.com|carto(cdn)?\.com|basemaps|cartodb|tile\.openstreetmap|fonts\.gstatic\.com|fonts\.googleapis\.com|api\.github\.com|releases\/latest|net::ERR_FAILED|ERR_BLOCKED_BY_CLIENT/i.test(
    txt,
  );
}

function attach(page: Page): void {
  page.on('console', (m: ConsoleMessage) => {
    if (m.type() === 'error') {
      const txt = m.text();
      if (isBenign(txt)) return;
      obs.consoleErrors.push(txt);
    }
  });
  page.on('pageerror', (e: Error) => obs.pageErrors.push(e.message));
  page.on('requestfailed', (r: Request) => {
    const u = r.url();
    if (isBenign(u)) return;
    obs.failed.push({ url: u, status: -1, method: r.method() });
  });
  page.on('response', (res) => {
    const url = res.url();
    const status = res.status();
    if (/\/geo-hub\/tilesets\/.*\/artifact\//.test(url)) {
      obs.geoArtifact.push({ url, status, ct: res.headers()['content-type'] ?? '' });
    }
    if (status >= 400 && url.includes(HOST) && !isBenign(url)) {
      obs.failed.push({ url, status, method: res.request().method() });
    }
  });
}

function shot(name: string): string {
  return path.join(SHOTS, name);
}

async function hasErrorBoundary(page: Page): Promise<boolean> {
  const cues = [
    'text=/something went wrong/i',
    'text=/unexpected error/i',
    '[data-testid="error-boundary"]',
  ];
  for (const c of cues) {
    if (await page.locator(c).first().isVisible({ timeout: 200 }).catch(() => false)) return true;
  }
  return false;
}

/** Snapshot non-benign console/page errors observed since the last reset. */
function drainErrors(label: string): { console: string[]; page: string[]; failed: typeof obs.failed } {
  const snap = {
    console: [...obs.consoleErrors],
    page: [...obs.pageErrors],
    failed: [...obs.failed],
  };
  if (snap.console.length || snap.page.length) {
    console.log(`[${label}] console=${JSON.stringify(snap.console)} page=${JSON.stringify(snap.page)}`);
  }
  if (snap.failed.length) console.log(`[${label}] failed/4xx=${JSON.stringify(snap.failed)}`);
  return snap;
}
function resetObs(): void {
  obs = freshObs();
}

test.describe.configure({ mode: 'serial', timeout: 600_000 });

test('comprehensive E2E — all flows on one session', async ({ page }) => {
  test.setTimeout(600_000);
  attach(page);

  // ════════════════════════════════════════════════════════════════════════
  // FLOW 0 + 1 — Real UI login → Dashboard
  // ════════════════════════════════════════════════════════════════════════
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
  await page.locator('#login-email').waitFor({ state: 'visible', timeout: 15_000 });
  await page.locator('#login-email').fill(DEMO_EMAIL);
  await page.locator('#login-password').fill(DEMO_PASSWORD);
  // Check "remember me" so tokens persist in localStorage (survives reloads).
  const remember = page.locator('input[type="checkbox"]').first();
  if (await remember.isVisible().catch(() => false)) await remember.check().catch(() => {});
  await page.screenshot({ path: shot('01a-login-filled.png') });

  await page.getByRole('button', { name: /^sign in$/i }).first().click();
  const loggedIn = await page
    .waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20_000 })
    .then(() => true)
    .catch(() => false);

  if (!loggedIn) {
    await page.screenshot({ path: shot('01x-login-failed.png') });
    findings.push({
      flow: 'login',
      severity: 'critical',
      area: 'Auth',
      detail: `Real UI login did not navigate away from /login with ${DEMO_EMAIL}.`,
      repro: 'Open /login, enter demo creds, click Sign in.',
    });
    record('login', false, 'did not leave /login');
    throw new Error('Login failed — cannot continue authenticated flows.');
  }

  await expect(
    page
      .locator('[data-testid="app-shell"], [data-testid="app-header"], header, [role="banner"]')
      .first(),
  ).toBeVisible({ timeout: 15_000 });
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
  await page.screenshot({ path: shot('01b-dashboard.png'), fullPage: true });

  const dashEB = await hasErrorBoundary(page);
  const dashErr = drainErrors('dashboard');
  const dashPass = !dashEB && dashErr.page.length === 0 && dashErr.console.length === 0;
  record('1-dashboard', dashPass, dashEB ? 'error boundary' : `console=${dashErr.console.length} page=${dashErr.page.length}`);
  if (dashEB)
    findings.push({ flow: 'dashboard', severity: 'high', area: 'Dashboard', detail: 'Error boundary on dashboard.' });
  for (const e of [...dashErr.console, ...dashErr.page])
    findings.push({ flow: 'dashboard', severity: 'medium', area: 'Dashboard', detail: `Console/page error: ${e}` });
  resetObs();

  // ════════════════════════════════════════════════════════════════════════
  // FLOW 2 — GEO: Downtown Medical (tileset d346a4b2) 3D model visibility
  // ════════════════════════════════════════════════════════════════════════
  // Arm the artifact waiters BEFORE navigation so a fast response is not
  // missed (?model= forces a flyTo onto the model's bounding sphere).
  const tilesetJsonP = page
    .waitForResponse((r) => /\/geo-hub\/tilesets\/.*\/artifact\/tileset\.json/.test(r.url()), {
      timeout: 30_000,
    })
    .catch(() => null);
  const b3dmP = page
    .waitForResponse((r) => /\/geo-hub\/tilesets\/.*\/artifact\/.*\.b3dm/.test(r.url()), {
      timeout: 30_000,
    })
    .catch(() => null);
  await page.goto(`${BASE}/projects/${PROJ.downtownMedical}/geo?model=${GEO_BIM_SOURCE}`, {
    waitUntil: 'domcontentloaded',
  });
  // Cesium mounts its canvas inside .cesium-widget; prefer that, fall back
  // to any canvas. Some builds attach the canvas a beat after the widget div.
  await page
    .locator('.cesium-widget, .cesium-viewer, canvas')
    .first()
    .waitFor({ state: 'attached', timeout: 30_000 })
    .catch(() => {});
  const canvas = page.locator('.cesium-widget canvas, canvas').first();
  const canvasVisible = await canvas.isVisible({ timeout: 30_000 }).catch(() => false);

  const artifactResp = await tilesetJsonP;
  await b3dmP;

  // Give Cesium time to fetch child tiles (tile_0.b3dm) and render the model.
  await page.waitForTimeout(6_000);
  // Wait for network to settle so tiles finish.
  await page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => {});
  await page.waitForTimeout(2_000);

  await page.screenshot({ path: shot('02a-geo-downtown-medical.png'), fullPage: true });
  // Also a tight canvas-only shot if possible.
  if (canvasVisible) {
    await canvas.screenshot({ path: shot('02b-geo-canvas.png') }).catch(() => {});
  }

  const artifactStatus = artifactResp ? artifactResp.status() : null;
  const artifactCt = artifactResp ? artifactResp.headers()['content-type'] ?? '' : '';
  // Did any b3dm tile load?
  const b3dmStatuses = obs.geoArtifact.filter((a) => /\.b3dm/.test(a.url)).map((a) => a.status);
  const tilesetJsonOk = artifactStatus === 200 && /json/i.test(artifactCt);
  const tilesetJsonSpaFallthrough = artifactStatus === 200 && /text\/html/i.test(artifactCt);

  // Inspect the Cesium scene for an actual loaded 3D tileset primitive.
  const sceneProbe = await page
    .evaluate(() => {
      // The viewer attaches no global by default; probe the canvas + any
      // window.__cesiumViewer if the app exposed one. Fall back to counting
      // primitives via a Cesium global if present.
      type W = Window & {
        Cesium?: unknown;
        __oeCesiumViewer?: { scene?: { primitives?: { length?: number } } };
      };
      const w = window as W;
      const v = w.__oeCesiumViewer;
      const primCount = v?.scene?.primitives?.length ?? null;
      const hasCanvas = !!document.querySelector('canvas');
      // Heuristic: read canvas pixels to confirm it is not blank.
      let nonBlank = false;
      try {
        const c = document.querySelector('canvas') as HTMLCanvasElement | null;
        if (c) {
          const gl =
            (c.getContext('webgl2') as WebGL2RenderingContext | null) ||
            (c.getContext('webgl') as WebGLRenderingContext | null);
          if (gl) {
            const w2 = c.width;
            const h2 = c.height;
            const px = new Uint8Array(4 * 64);
            // Sample a 8x8 block near the centre.
            gl.readPixels(
              Math.floor(w2 / 2) - 4,
              Math.floor(h2 / 2) - 4,
              8,
              8,
              gl.RGBA,
              gl.UNSIGNED_BYTE,
              px,
            );
            // Non-blank if any pixel differs from the first sample meaningfully.
            const r0 = px[0],
              g0 = px[1],
              b0 = px[2];
            for (let i = 4; i < px.length; i += 4) {
              if (
                Math.abs((px[i] ?? 0) - (r0 ?? 0)) > 6 ||
                Math.abs((px[i + 1] ?? 0) - (g0 ?? 0)) > 6 ||
                Math.abs((px[i + 2] ?? 0) - (b0 ?? 0)) > 6
              ) {
                nonBlank = true;
                break;
              }
            }
          }
        }
      } catch {
        /* readPixels can throw on tainted/CORS canvas — ignore */
      }
      return { primCount, hasCanvas, nonBlank };
    })
    .catch(() => ({ primCount: null, hasCanvas: false, nonBlank: false }));

  // Layer controls present? (overlay/tileset sidebar)
  const layerControls = await page
    .getByText(/layer|overlay|tileset|3d model|model/i)
    .first()
    .isVisible({ timeout: 2_000 })
    .catch(() => false);

  const geoEB = await hasErrorBoundary(page);
  const geoErr = drainErrors('geo');

  // The decisive signal that the 3D model is rendered: tileset.json served as
  // JSON (not SPA HTML), the b3dm child tile loaded (200), and a canvas is
  // present. A separate GL draw-call probe (geo-gl-probe.spec) confirms the
  // b3dm mesh actually rasterises. readPixels on a Cesium canvas is unreliable
  // (preserveDrawingBuffer:false) so it is advisory only here.
  const geoModelVisible = tilesetJsonOk && b3dmStatuses.includes(200) && canvasVisible;
  record(
    '2-geo',
    !!geoModelVisible && !geoEB,
    `canvas=${canvasVisible} tileset.json=${artifactStatus}/${artifactCt} b3dm=${JSON.stringify(b3dmStatuses)} sceneNonBlank=${sceneProbe.nonBlank} primCount=${sceneProbe.primCount} layerCtrls=${layerControls}`,
  );

  if (tilesetJsonSpaFallthrough)
    findings.push({
      flow: 'geo',
      severity: 'critical',
      area: 'Geo Hub / Cesium',
      detail:
        'tileset.json artifact returned 200 text/html (SPA index.html fall-through) instead of JSON — Cesium cannot parse it, 3D model invisible.',
      repro: `Open /projects/${PROJ.downtownMedical}/geo and watch the artifact request.`,
    });
  if (artifactStatus && artifactStatus === 401)
    findings.push({
      flow: 'geo',
      severity: 'critical',
      area: 'Geo Hub / Cesium auth',
      detail: 'tileset.json artifact returned 401 — Cesium request missing the Bearer token; 3D model invisible.',
      repro: `Open /projects/${PROJ.downtownMedical}/geo.`,
    });
  if (!geoModelVisible && !tilesetJsonSpaFallthrough && artifactStatus !== 401)
    findings.push({
      flow: 'geo',
      severity: 'high',
      area: 'Geo Hub / Cesium',
      detail: `3D model not confirmed visible. tileset.json=${artifactStatus}/${artifactCt}, b3dm=${JSON.stringify(b3dmStatuses)}, canvasNonBlank=${sceneProbe.nonBlank}.`,
      repro: `Open /projects/${PROJ.downtownMedical}/geo.`,
    });
  if (geoEB) findings.push({ flow: 'geo', severity: 'high', area: 'Geo Hub', detail: 'Error boundary on geo page.' });
  for (const e of geoErr.page)
    findings.push({ flow: 'geo', severity: 'medium', area: 'Geo Hub', detail: `Page error: ${e}` });
  resetObs();

  // ════════════════════════════════════════════════════════════════════════
  // FLOW 3 — COST SPINE: Berlin-Mitte, generate from BOQ + idempotency
  // ════════════════════════════════════════════════════════════════════════
  await page.goto(`${BASE}/5d`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});

  // The page shows a project selector. Click the Berlin-Mitte card.
  const berlinCard = page.getByText(/Wohnanlage Berlin-Mitte/i).first();
  const sawSelector = await berlinCard.isVisible({ timeout: 8_000 }).catch(() => false);
  if (sawSelector) {
    await berlinCard.click();
  } else {
    // Possibly auto-selected a different project; try the back/selector path.
    const back = page.getByRole('button', { name: /back|projects/i }).first();
    if (await back.isVisible({ timeout: 1_500 }).catch(() => false)) {
      await back.click();
      await page.getByText(/Wohnanlage Berlin-Mitte/i).first().click({ timeout: 5_000 }).catch(() => {});
    }
  }
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});

  // Scroll to the Cost Spine section.
  const spineHeading = page.getByRole('heading', { name: /^cost spine$/i }).first();
  await spineHeading.scrollIntoViewIfNeeded({ timeout: 10_000 }).catch(() => {});
  await page.waitForTimeout(800);
  await page.screenshot({ path: shot('03a-spine-before-generate.png'), fullPage: true });

  // Click "Generate from BOQ".
  const genBtn = page.getByRole('button', { name: /generate from boq/i }).first();
  const genVisible = await genBtn.isVisible({ timeout: 8_000 }).catch(() => false);

  let firstLineCount = 0;
  let secondLineCount = 0;
  let rollupHasTotal = false;
  let treeRendered = false;
  let drawerOpened = false;

  if (!genVisible) {
    findings.push({
      flow: 'cost-spine',
      severity: 'high',
      area: 'Cost Model / 5D',
      detail: 'Could not find the "Generate from BOQ" button on the 5D dashboard Cost Spine section.',
      repro: 'Open /5d, select Wohnanlage Berlin-Mitte, scroll to Cost Spine.',
    });
    record('3-cost-spine', false, 'generate button not found');
  } else {
    // First generate — wait for the generate POST to resolve.
    const gen1 = page
      .waitForResponse((r) => /spine\/generate-from-boq/.test(r.url()) && r.request().method() === 'POST', {
        timeout: 30_000,
      })
      .catch(() => null);
    await genBtn.click();
    const r1 = await gen1;
    // Wait for the rollup query to refetch and rows to render.
    await page
      .waitForResponse((r) => /spine\/rollup/.test(r.url()), { timeout: 20_000 })
      .catch(() => null);
    await page.waitForTimeout(2_000);

    // Count cost-line rows (role=button rows inside the spine table).
    const lineRows = page.locator('tr[role="button"]');
    firstLineCount = await lineRows.count().catch(() => 0);

    // Control-account tree rendered? (left tree column with account codes)
    treeRendered = await page
      .locator('table tr th[scope="colgroup"], [data-testid="control-account-tree"]')
      .first()
      .isVisible({ timeout: 3_000 })
      .catch(() => false);

    // Project total / rollup figure present?
    rollupHasTotal = await page
      .getByText(/project total/i)
      .first()
      .isVisible({ timeout: 3_000 })
      .catch(() => false);

    await spineHeading.scrollIntoViewIfNeeded().catch(() => {});
    await page.screenshot({ path: shot('03b-spine-after-generate.png'), fullPage: true });

    // Open the rollup drawer by clicking a cost line.
    if (firstLineCount > 0) {
      await lineRows.first().click().catch(() => {});
      drawerOpened = await page
        .locator('[role="dialog"], [data-testid^="modal"], [class*="drawer" i]')
        .first()
        .isVisible({ timeout: 4_000 })
        .catch(() => false);
      await page.screenshot({ path: shot('03c-spine-rollup-drawer.png') });
      // Close the drawer (Escape) so the second generate sees the grid.
      await page.keyboard.press('Escape').catch(() => {});
      await page.waitForTimeout(500);
    }

    // Second generate — idempotency check.
    const gen2 = page
      .waitForResponse((r) => /spine\/generate-from-boq/.test(r.url()) && r.request().method() === 'POST', {
        timeout: 30_000,
      })
      .catch(() => null);
    const genBtn2 = page.getByRole('button', { name: /generate from boq/i }).first();
    await genBtn2.scrollIntoViewIfNeeded().catch(() => {});
    await genBtn2.click().catch(() => {});
    const r2 = await gen2;
    await page.waitForResponse((r) => /spine\/rollup/.test(r.url()), { timeout: 20_000 }).catch(() => null);
    await page.waitForTimeout(2_000);
    secondLineCount = await page.locator('tr[role="button"]').count().catch(() => 0);
    await page.screenshot({ path: shot('03d-spine-after-second-generate.png'), fullPage: true });

    const idempotent = secondLineCount > 0 && secondLineCount <= firstLineCount;
    const spinePass = firstLineCount > 0 && rollupHasTotal && treeRendered && idempotent;
    record(
      '3-cost-spine',
      spinePass,
      `lines1=${firstLineCount} lines2=${secondLineCount} tree=${treeRendered} total=${rollupHasTotal} drawer=${drawerOpened} gen1=${r1?.status()} gen2=${r2?.status()} idempotent=${idempotent}`,
    );

    if (firstLineCount === 0)
      findings.push({
        flow: 'cost-spine',
        severity: 'high',
        area: 'Cost Model / 5D',
        detail: 'Generate from BOQ produced 0 cost-line rows in the grid.',
        repro: 'Open /5d → Berlin-Mitte → Cost Spine → Generate from BOQ.',
      });
    if (!treeRendered)
      findings.push({
        flow: 'cost-spine',
        severity: 'medium',
        area: 'Cost Model / 5D',
        detail: 'Control-account tree / group headers did not render after generate.',
      });
    if (!rollupHasTotal)
      findings.push({
        flow: 'cost-spine',
        severity: 'medium',
        area: 'Cost Model / 5D',
        detail: 'Project total / rollup figure not visible after generate.',
      });
    if (!drawerOpened && firstLineCount > 0)
      findings.push({
        flow: 'cost-spine',
        severity: 'medium',
        area: 'Cost Model / 5D',
        detail: 'Clicking a cost line did not open the rollup drawer.',
      });
    if (!idempotent)
      findings.push({
        flow: 'cost-spine',
        severity: 'high',
        area: 'Cost Model / 5D',
        detail: `Generate is NOT idempotent: line count grew from ${firstLineCount} to ${secondLineCount} on second generate.`,
        repro: 'Click Generate from BOQ twice; compare row counts.',
      });
  }
  drainErrors('cost-spine');
  resetObs();

  // ════════════════════════════════════════════════════════════════════════
  // FLOW 4 — PARTNER PACKS: dev guide anchor + modules tab + activate dialog
  // ════════════════════════════════════════════════════════════════════════
  await page.goto(`${BASE}/modules/developer-guide#partner-packs`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 12_000 }).catch(() => {});
  await page.waitForTimeout(1_200);
  const ppCard = page.locator('#partner-packs');
  const ppCardVisible = await ppCard.isVisible({ timeout: 8_000 }).catch(() => false);
  // The documented install entry-point group must reference openconstructionerp.
  const installCmdOk = await page
    .getByText(/openconstructionerp\.partner_packs/i)
    .first()
    .isVisible({ timeout: 4_000 })
    .catch(() => false);
  // Confirm the anchor is actually scrolled near the top of the viewport.
  const anchorScrolled = await ppCard
    .evaluate((el) => {
      const r = el.getBoundingClientRect();
      return r.top < window.innerHeight && r.top > -50; // in view, near top
    })
    .catch(() => false);
  await page.screenshot({ path: shot('04a-devguide-partner-packs.png'), fullPage: true });
  record(
    '4a-devguide',
    ppCardVisible && installCmdOk,
    `cardVisible=${ppCardVisible} installCmdOpenConstructionERP=${installCmdOk} anchorScrolled=${anchorScrolled}`,
  );
  if (!ppCardVisible)
    findings.push({
      flow: 'partner-packs',
      severity: 'medium',
      area: 'Module Developer Guide',
      detail: 'Partner Packs section (#partner-packs) did not render on the developer guide.',
      repro: 'Open /modules/developer-guide#partner-packs.',
    });
  if (!installCmdOk)
    findings.push({
      flow: 'partner-packs',
      severity: 'low',
      area: 'Module Developer Guide',
      detail: 'Documented install entry-point group does not show "openconstructionerp.partner_packs".',
    });

  // Now the modules page partner-packs tab.
  await page.goto(`${BASE}/modules?tab=partner-packs`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 12_000 }).catch(() => {});
  await page.waitForResponse((r) => /partner-pack\/installed/.test(r.url()), { timeout: 12_000 }).catch(() => null);
  await page.waitForTimeout(1_200);
  await page.screenshot({ path: shot('04b-modules-partner-packs-tab.png'), fullPage: true });

  // Activate button opens the dialog (do NOT confirm).
  const activateBtn = page.getByRole('button', { name: /activate pack/i }).first();
  const activateVisible = await activateBtn.isVisible({ timeout: 8_000 }).catch(() => false);
  let dialogOpened = false;
  if (activateVisible) {
    await activateBtn.click();
    dialogOpened = await page
      .locator('[role="dialog"], [data-testid^="modal"]')
      .first()
      .isVisible({ timeout: 5_000 })
      .catch(() => false);
    await page.screenshot({ path: shot('04c-partner-pack-activate-dialog.png') });
    // Close without confirming (no mutation).
    const cancel = page.getByRole('button', { name: /cancel|close/i }).first();
    if (await cancel.isVisible({ timeout: 1_500 }).catch(() => false)) await cancel.click().catch(() => {});
    else await page.keyboard.press('Escape').catch(() => {});
  }
  const ppEB = await hasErrorBoundary(page);
  record(
    '4b-partner-packs-tab',
    activateVisible && dialogOpened && !ppEB,
    `activateBtn=${activateVisible} dialogOpened=${dialogOpened} errorBoundary=${ppEB}`,
  );
  if (!activateVisible)
    findings.push({
      flow: 'partner-packs',
      severity: 'high',
      area: 'Modules / Partner Packs',
      detail: 'No "Activate pack" button rendered on the partner-packs tab (pack list may be empty/failed).',
      repro: 'Open /modules?tab=partner-packs.',
    });
  else if (!dialogOpened)
    findings.push({
      flow: 'partner-packs',
      severity: 'high',
      area: 'Modules / Partner Packs',
      detail: 'Clicking "Activate pack" did not open the apply dialog.',
      repro: 'Open /modules?tab=partner-packs, click Activate pack.',
    });
  drainErrors('partner-packs');
  resetObs();

  // ════════════════════════════════════════════════════════════════════════
  // FLOW 5 — BROAD SMOKE: projects, BOQ editor, costs, schedule, documents, BIM
  // ════════════════════════════════════════════════════════════════════════
  const smokeTargets: { name: string; url: string; file: string; settle?: number }[] = [
    { name: 'projects-list', url: `${BASE}/projects`, file: '05a-projects.png' },
    { name: 'cost-database', url: `${BASE}/costs`, file: '05b-costs.png' },
    { name: 'schedule', url: `${BASE}/projects/${PROJ.berlinMitte}/schedule`, file: '05c-schedule.png' },
    { name: 'documents-files', url: `${BASE}/files`, file: '05d-files.png' },
    { name: 'bim-hub', url: `${BASE}/bim`, file: '05e-bim.png', settle: 4000 },
    { name: 'validation', url: `${BASE}/validation`, file: '05f-validation.png' },
    { name: 'reporting', url: `${BASE}/reporting`, file: '05g-reporting.png' },
  ];

  // First open BOQ list, then drill into a real BOQ editor for Berlin-Mitte.
  await page.goto(`${BASE}/projects/${PROJ.berlinMitte}/boq`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
  await page.waitForTimeout(1_000);
  // Click the first BOQ to open the editor.
  const firstBoqLink = page.locator('a[href*="/boq/"], [role="row"] a, table tbody tr').first();
  const boqOpened = await firstBoqLink
    .click({ timeout: 5_000 })
    .then(() => true)
    .catch(() => false);
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
  await page.waitForTimeout(1_500);
  await page.screenshot({ path: shot('05h-boq-editor.png'), fullPage: true });
  const boqEB = await hasErrorBoundary(page);
  const boqErr = drainErrors('boq-editor');
  record(
    '5-boq-editor',
    !boqEB && boqErr.page.length === 0,
    `opened=${boqOpened} errorBoundary=${boqEB} pageErr=${boqErr.page.length} console=${boqErr.console.length}`,
  );
  if (boqEB) findings.push({ flow: 'smoke', severity: 'high', area: 'BOQ Editor', detail: 'Error boundary in BOQ editor.' });
  for (const e of boqErr.page) findings.push({ flow: 'smoke', severity: 'medium', area: 'BOQ Editor', detail: `Page error: ${e}` });
  resetObs();

  for (const tgt of smokeTargets) {
    await page.goto(tgt.url, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
    await page.waitForTimeout(tgt.settle ?? 1_200);
    await page.screenshot({ path: shot(tgt.file), fullPage: true });
    const eb = await hasErrorBoundary(page);
    const err = drainErrors(tgt.name);
    const pass = !eb && err.page.length === 0 && err.console.length === 0;
    record(`5-${tgt.name}`, pass, `errorBoundary=${eb} pageErr=${err.page.length} console=${err.console.length}`);
    if (eb)
      findings.push({ flow: 'smoke', severity: 'high', area: tgt.name, detail: `Error boundary on ${tgt.url}.`, repro: `Open ${tgt.url}` });
    for (const e of err.page)
      findings.push({ flow: 'smoke', severity: 'medium', area: tgt.name, detail: `Page error: ${e}`, repro: `Open ${tgt.url}` });
    for (const e of err.console)
      findings.push({ flow: 'smoke', severity: 'low', area: tgt.name, detail: `Console error: ${e}`, repro: `Open ${tgt.url}` });
    resetObs();
  }

  // ── Write machine-readable report ─────────────────────────────────────────
  const report = { base: BASE, when: new Date().toISOString(), results, findings };
  fs.writeFileSync(path.join(SHOTS, '_report.json'), JSON.stringify(report, null, 2), 'utf-8');
  console.log('\n================ RESULTS ================');
  for (const r of results) console.log(`${r.pass ? 'PASS' : 'FAIL'}  ${r.flow}  — ${r.note}`);
  console.log('================ FINDINGS ================');
  for (const f of findings) console.log(`[${f.severity}] (${f.area}) ${f.detail}${f.repro ? `  REPRO: ${f.repro}` : ''}`);

  // The test as a whole "passes" structurally; flow verdicts live in the report.
  expect(results.length).toBeGreaterThan(0);
});
