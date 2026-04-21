/**
 * Full Journey Audit — deep E2E probe for every major route.
 *
 * Goal: find every user-facing error an end user would hit.
 *
 * For each route:
 *   1. Navigate (or click into) the page
 *   2. Actually interact (click buttons, open modals, fill forms, upload files)
 *   3. Log every 4xx/5xx HTTP response
 *   4. Log every console error (filtered to meaningful ones)
 *   5. Log every visible error toast
 *   6. Take a screenshot
 *
 * Tests are wrapped in try/catch so failures in one route do NOT abort others.
 * At the end, a summary file is written to test-results/audit-findings.json.
 *
 * Run:
 *   cd frontend && npx playwright test e2e/full-journey-audit.spec.ts \
 *     --workers=1 --reporter=line --timeout=120000
 */

import { test, expect, type Page, type Request, type Response, type ConsoleMessage } from '@playwright/test';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Run serially — shared browser state, shared backend user pool
test.describe.configure({ mode: 'serial' });

/* ── Types ─────────────────────────────────────────────────────────────── */

interface HttpFailure {
  url: string;
  method: string;
  status: number;
  statusText: string;
}

interface ConsoleError {
  text: string;
  location?: string;
}

interface ToastError {
  text: string;
}

interface RouteFinding {
  route: string;
  label: string;
  ok: boolean;
  durationMs: number;
  httpFailures: HttpFailure[];
  consoleErrors: ConsoleError[];
  toastErrors: ToastError[];
  uxIssues: string[];
  screenshot?: string;
  error?: string;
}

const allFindings: RouteFinding[] = [];

/* ── Auth helper (copy of injectAuth from bim-advanced.spec.ts) ────────── */

interface AuthTokens {
  accessToken: string;
  refreshToken: string;
  email: string;
  role: string;
  newAdminEmail?: string;
}

let cachedAuth: AuthTokens | null = null;

async function acquireAuth(page: Page): Promise<AuthTokens> {
  if (cachedAuth) return cachedAuth;

  // Step 1: Login the existing viewer user (test@openestimate.com)
  const loginRes = await page.request.post('http://localhost:8000/api/v1/users/auth/login/', {
    data: { email: 'test@openestimate.com', password: 'OpenEstimate2024!' },
  });

  let accessToken: string;
  let refreshToken: string;
  let role = 'unknown';

  if (loginRes.ok()) {
    const body = await loginRes.json();
    accessToken = body.access_token;
    refreshToken = body.refresh_token || body.access_token;
  } else {
    // Register then login
    await page.request.post('http://localhost:8000/api/v1/users/auth/register/', {
      data: { email: 'test@openestimate.com', password: 'OpenEstimate2024!', full_name: 'E2E Audit' },
    });
    const retry = await page.request.post('http://localhost:8000/api/v1/users/auth/login/', {
      data: { email: 'test@openestimate.com', password: 'OpenEstimate2024!' },
    });
    const body = await retry.json();
    accessToken = body.access_token;
    refreshToken = body.refresh_token || body.access_token;
  }

  // Step 2: Try to get current user role
  try {
    const meRes = await page.request.get('http://localhost:8000/api/v1/users/me/', {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (meRes.ok()) {
      const me = await meRes.json();
      role = me.role || 'unknown';
    }
  } catch {
    /* ignore */
  }

  // Step 3: Register a NEW unique admin-attempt user (will still be viewer on existing-admin DB)
  const ts = Date.now();
  const newAdminEmail = `admin-audit-${ts}@example.com`;
  try {
    await page.request.post('http://localhost:8000/api/v1/users/auth/register/', {
      data: {
        email: newAdminEmail,
        password: 'AuditAdmin2024!',
        full_name: 'Audit Admin',
      },
    });
  } catch {
    /* ignore — user may fail to register */
  }

  cachedAuth = {
    accessToken,
    refreshToken,
    email: 'test@openestimate.com',
    role,
    newAdminEmail,
  };
  return cachedAuth;
}

async function injectAuth(page: Page): Promise<AuthTokens> {
  const auth = await acquireAuth(page);
  await page.addInitScript((tokens: { access: string; refresh: string; email: string }) => {
    localStorage.setItem('oe_access_token', tokens.access);
    localStorage.setItem('oe_refresh_token', tokens.refresh);
    localStorage.setItem('oe_remember', '1');
    localStorage.setItem('oe_user_email', tokens.email);
    localStorage.setItem('oe_onboarding_completed', 'true');
    localStorage.setItem('oe_welcome_dismissed', 'true');
    localStorage.setItem('oe_tour_completed', 'true');
    sessionStorage.setItem('oe_access_token', tokens.access);
    sessionStorage.setItem('oe_refresh_token', tokens.refresh);
  }, { access: auth.accessToken, refresh: auth.refreshToken, email: auth.email });

  await page.goto('/about');
  await page.waitForLoadState('load');
  await page.waitForTimeout(500);
  return auth;
}

/* ── Tracker helpers ───────────────────────────────────────────────────── */

class RouteTracker {
  route: string;
  label: string;
  httpFailures: HttpFailure[] = [];
  consoleErrors: ConsoleError[] = [];
  toastErrors: ToastError[] = [];
  uxIssues: string[] = [];
  start = Date.now();

  private onResponse: (r: Response) => void;
  private onConsole: (m: ConsoleMessage) => void;
  private onPageError: (e: Error) => void;

  constructor(route: string, label: string, private page: Page) {
    this.route = route;
    this.label = label;

    this.onResponse = (res: Response) => {
      const status = res.status();
      if (status >= 400 && status < 600) {
        const url = res.url();
        // Ignore external requests & favicons & sourcemaps
        if (
          url.includes('favicon') ||
          url.endsWith('.map') ||
          url.includes('/@vite/') ||
          url.includes('__vite') ||
          url.includes('analytics.google') ||
          url.includes('sentry.io')
        ) {
          return;
        }
        this.httpFailures.push({
          url: url.length > 150 ? url.slice(0, 150) + '…' : url,
          method: res.request().method(),
          status,
          statusText: res.statusText(),
        });
      }
    };

    this.onConsole = (msg: ConsoleMessage) => {
      if (msg.type() !== 'error') return;
      const text = msg.text();
      // Filter noise that isn't actionable
      if (
        text.includes('Failed to load resource') ||
        text.includes('favicon') ||
        text.includes('downloadable font') ||
        text.includes('Warning: ') ||
        text.includes('[HMR]') ||
        text.includes('[vite]') ||
        text.includes('React DevTools') ||
        /^\s*$/.test(text)
      ) {
        return;
      }
      const loc = msg.location();
      this.consoleErrors.push({
        text: text.length > 300 ? text.slice(0, 300) + '…' : text,
        location: loc?.url ? `${loc.url}:${loc.lineNumber ?? '?'}` : undefined,
      });
    };

    this.onPageError = (e: Error) => {
      this.consoleErrors.push({ text: `[pageerror] ${e.message}` });
    };

    page.on('response', this.onResponse);
    page.on('console', this.onConsole);
    page.on('pageerror', this.onPageError);
  }

  detach(): void {
    try {
      this.page.off('response', this.onResponse);
      this.page.off('console', this.onConsole);
      this.page.off('pageerror', this.onPageError);
    } catch {
      /* ignore */
    }
  }

  async captureToasts(): Promise<void> {
    // Check for known error-toast patterns
    const selectors = [
      '[data-testid="toast-error"]',
      '[role="alert"]',
      '.toast-error',
      '[class*="toast"][class*="error"]',
      '[class*="notification"][class*="error"]',
      '.Toastify__toast--error',
      'text=/error|failed|fehler|ошибка/i',
    ];
    for (const sel of selectors) {
      try {
        const els = this.page.locator(sel);
        const count = await els.count();
        for (let i = 0; i < Math.min(count, 5); i++) {
          const t = (await els.nth(i).textContent({ timeout: 300 }).catch(() => null))?.trim();
          if (t && t.length > 0 && t.length < 400 && !this.toastErrors.some(e => e.text === t)) {
            this.toastErrors.push({ text: t });
          }
        }
      } catch {
        /* ignore */
      }
    }
  }

  noteUx(issue: string): void {
    this.uxIssues.push(issue);
  }

  finalize(screenshot?: string, error?: string): RouteFinding {
    this.detach();
    return {
      route: this.route,
      label: this.label,
      ok: this.httpFailures.length === 0 && this.consoleErrors.length === 0 && this.toastErrors.length === 0 && !error,
      durationMs: Date.now() - this.start,
      httpFailures: this.httpFailures,
      consoleErrors: this.consoleErrors,
      toastErrors: this.toastErrors,
      uxIssues: this.uxIssues,
      screenshot,
      error,
    };
  }
}

async function safeScreenshot(page: Page, name: string): Promise<string | undefined> {
  const file = `test-results/audit-${name}.png`;
  try {
    await page.screenshot({ path: file, fullPage: false, timeout: 10000 });
    return file;
  } catch {
    return undefined;
  }
}

async function dismissTour(page: Page): Promise<void> {
  try {
    const dismissBtns = [
      page.locator('button:has-text("Skip")').first(),
      page.locator('button:has-text("Got it")').first(),
      page.locator('button:has-text("Close")').first(),
      page.locator('button:has-text("Next")').first(),
      page.locator('[aria-label="Close"]').first(),
    ];
    for (const btn of dismissBtns) {
      if (await btn.isVisible({ timeout: 300 }).catch(() => false)) {
        await btn.click({ timeout: 500 }).catch(() => {});
        await page.waitForTimeout(150);
      }
    }
  } catch {
    /* ignore */
  }
}

async function runRoute(
  page: Page,
  slug: string,
  label: string,
  route: string,
  interact: (page: Page, tr: RouteTracker) => Promise<void>,
): Promise<void> {
  const tr = new RouteTracker(route, label, page);
  let err: string | undefined;
  try {
    await page.goto(route, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await page.waitForTimeout(1500);
    await dismissTour(page);
    await interact(page, tr);
    await page.waitForTimeout(800);
    await tr.captureToasts();
  } catch (e: any) {
    err = e?.message?.slice(0, 300) ?? String(e);
    tr.noteUx(`Exception during interaction: ${err}`);
  }
  const shot = await safeScreenshot(page, slug);
  allFindings.push(tr.finalize(shot, err));
}

/* ── Test suite ─────────────────────────────────────────────────────────── */

test.describe('Full Journey Audit', () => {
  test.beforeEach(async ({ page }) => {
    await injectAuth(page);
  });

  test('A1: Dashboard (/)', async ({ page }) => {
    await runRoute(page, '01-dashboard', 'Dashboard', '/', async (p, tr) => {
      // Look for KPI cards / tiles
      const kpiCards = p.locator('[data-testid*="kpi"], [class*="kpi"], [class*="stat-card"], [class*="metric-card"]');
      const kpiCount = await kpiCards.count();
      if (kpiCount === 0) tr.noteUx('No KPI cards found on dashboard');
      else {
        // Click first 2 KPI cards if clickable
        for (let i = 0; i < Math.min(kpiCount, 2); i++) {
          try {
            const c = kpiCards.nth(i);
            if (await c.isVisible().catch(() => false)) {
              await c.click({ trial: true, timeout: 1000 }).catch(() => {});
            }
          } catch { /* ignore */ }
        }
      }

      // Check for Quick Start section
      const qs = p.locator('text=/Quick Start|Getting Started|Welcome/i');
      if ((await qs.count()) === 0) tr.noteUx('No Quick Start / Welcome section visible');

      // Check for spinner that never resolves
      const spinners = p.locator('[class*="spinner"], [class*="loading"], [role="progressbar"]');
      await p.waitForTimeout(3000);
      const stuck = await spinners.count();
      if (stuck > 3) tr.noteUx(`${stuck} spinners still visible after 3s`);
    });
  });

  test('A2: Projects (/projects)', async ({ page }) => {
    await runRoute(page, '02-projects', 'Projects list + new project', '/projects', async (p, tr) => {
      // Click "New Project" if present
      const newBtn = p.locator('button:has-text("New Project"), button:has-text("Create Project"), button:has-text("Add Project"), a:has-text("New Project")').first();
      if (await newBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await newBtn.click().catch(() => {});
        await p.waitForTimeout(800);

        // Try to fill name field
        const nameInput = p.locator('input[name="name"], input[placeholder*="name" i]').first();
        if (await nameInput.isVisible({ timeout: 2000 }).catch(() => false)) {
          await nameInput.fill(`Audit Project ${Date.now()}`).catch(() => {});
        } else {
          tr.noteUx('New Project modal opened but no name input found');
        }

        // Click Save/Create submit
        const saveBtn = p.locator('button:has-text("Save"), button:has-text("Create"), button[type="submit"]').last();
        if (await saveBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
          await saveBtn.click().catch(() => {});
          await p.waitForTimeout(1500);
        }
      } else {
        tr.noteUx('No "New Project" button visible');
      }
    });
  });

  test('A3: BOQ (/boq)', async ({ page }) => {
    await runRoute(page, '03-boq', 'BOQ list + open', '/boq', async (p, tr) => {
      await p.waitForTimeout(1500);
      // Try to click first row if list has items
      const rows = p.locator('tr[role="row"]:not([aria-rowindex="1"]), [data-testid*="boq-row"], [class*="boq-card"]');
      const n = await rows.count();
      if (n === 0) {
        tr.noteUx('BOQ list empty or not rendering rows');
      } else {
        await rows.first().click({ timeout: 2000 }).catch(() => {});
        await p.waitForTimeout(1200);
      }
    });
  });

  test('A4: Costs (/costs)', async ({ page }) => {
    await runRoute(page, '04-costs', 'Cost database', '/costs', async (p, tr) => {
      await p.waitForTimeout(1500);
      // Filter
      const search = p.locator('input[type="search"], input[placeholder*="earch" i]').first();
      if (await search.isVisible({ timeout: 2000 }).catch(() => false)) {
        await search.fill('concrete').catch(() => {});
        await p.waitForTimeout(800);
      } else {
        tr.noteUx('No search/filter input on costs page');
      }
      // Try to click a column header (sort)
      const colHead = p.locator('th[role="columnheader"], [class*="ag-header-cell"]').first();
      if (await colHead.isVisible({ timeout: 1500 }).catch(() => false)) {
        await colHead.click({ timeout: 1500 }).catch(() => {});
        await p.waitForTimeout(500);
      }
      // Export
      const exportBtn = p.locator('button:has-text("Export"), button:has-text("Download")').first();
      if (await exportBtn.isVisible({ timeout: 1500 }).catch(() => false)) {
        await exportBtn.click({ timeout: 1500 }).catch(() => {});
        await p.waitForTimeout(800);
      }
    });
  });

  test('A5: Takeoff measurements (/takeoff?tab=measurements)', async ({ page }) => {
    await runRoute(page, '05-takeoff', 'Takeoff — upload PDF', '/takeoff?tab=measurements', async (p, tr) => {
      await p.waitForTimeout(1500);

      const pdfPath = path.resolve(__dirname, '..', 'test-drawing.pdf');
      if (!fs.existsSync(pdfPath)) {
        tr.noteUx(`test-drawing.pdf not found at ${pdfPath}`);
        return;
      }

      // Find file input
      const fileInputs = p.locator('input[type="file"]');
      const count = await fileInputs.count();
      if (count === 0) {
        tr.noteUx('No file input on takeoff page');
        return;
      }

      // Use the first visible or accessible file input
      try {
        await fileInputs.first().setInputFiles(pdfPath);
        await p.waitForTimeout(3000);
      } catch (e: any) {
        tr.noteUx(`setInputFiles failed: ${e?.message?.slice(0, 120)}`);
      }
    });
  });

  test('A6: DWG Takeoff (/dwg-takeoff)', async ({ page }) => {
    await runRoute(page, '06-dwg-takeoff', 'DWG Takeoff — upload DXF', '/dwg-takeoff', async (p, tr) => {
      await p.waitForTimeout(1500);

      // Click "click to browse" or upload area
      const browse = p.locator('text=/click to browse|browse|Choose file|Upload|Select.*file/i').first();
      if (await browse.isVisible({ timeout: 2000 }).catch(() => false)) {
        await browse.click({ timeout: 1500 }).catch(() => {});
        await p.waitForTimeout(500);
      }

      const dxfPath = path.resolve(__dirname, 'fixtures', 'test.dxf');
      if (!fs.existsSync(dxfPath)) {
        tr.noteUx(`test.dxf not found at ${dxfPath}`);
        return;
      }
      const inputs = p.locator('input[type="file"]');
      if ((await inputs.count()) === 0) {
        tr.noteUx('No file input on DWG takeoff page');
        return;
      }
      try {
        await inputs.first().setInputFiles(dxfPath);
        await p.waitForTimeout(3000);
      } catch (e: any) {
        tr.noteUx(`DXF upload failed: ${e?.message?.slice(0, 120)}`);
      }
    });
  });

  test('A7: BIM (/bim)', async ({ page }) => {
    await runRoute(page, '07-bim', 'BIM model selector', '/bim', async (p, tr) => {
      await p.waitForTimeout(2000);
      // Open model selector
      const sel = p.locator('button:has-text("Select"), button:has-text("Model"), [aria-label*="select" i], select').first();
      if (await sel.isVisible({ timeout: 2000 }).catch(() => false)) {
        await sel.click({ timeout: 1500 }).catch(() => {});
        await p.waitForTimeout(800);
      } else {
        const modelCards = p.locator('[class*="model-card"], [data-testid*="model"]');
        if ((await modelCards.count()) === 0) tr.noteUx('No model selector and no model cards visible');
      }
    });
  });

  test('A8: Data Explorer (/data-explorer)', async ({ page }) => {
    await runRoute(page, '08-data-explorer', 'Data Explorer — upload', '/data-explorer', async (p, tr) => {
      await p.waitForTimeout(1500);
      const upl = p.locator('button:has-text("Upload"), button:has-text("Import"), input[type="file"]').first();
      if (await upl.isVisible({ timeout: 2000 }).catch(() => false)) {
        if (await upl.evaluate((el) => (el as HTMLInputElement).tagName?.toLowerCase() === 'input').catch(() => false)) {
          // It's an input — leave empty (upload tested on takeoff/dwg)
        } else {
          await upl.click({ timeout: 1000 }).catch(() => {});
          await p.waitForTimeout(500);
        }
      } else {
        tr.noteUx('No upload/import trigger on Data Explorer');
      }
    });
  });

  test('A9: Settings (/settings)', async ({ page }) => {
    await runRoute(page, '09-settings', 'Settings tabs + save', '/settings', async (p, tr) => {
      await p.waitForTimeout(1500);
      // Click through tabs
      const tabs = p.locator('[role="tab"], button[class*="tab"], a[class*="tab"]');
      const n = await tabs.count();
      if (n === 0) {
        tr.noteUx('No tabs found on settings page');
      } else {
        for (let i = 0; i < Math.min(n, 4); i++) {
          try {
            const t = tabs.nth(i);
            if (await t.isVisible().catch(() => false)) {
              await t.click({ timeout: 1500 }).catch(() => {});
              await p.waitForTimeout(400);
            }
          } catch { /* ignore */ }
        }
      }

      // Try to save
      const saveBtn = p.locator('button:has-text("Save"), button:has-text("Update"), button:has-text("Apply")').first();
      if (await saveBtn.isVisible({ timeout: 1500 }).catch(() => false)) {
        await saveBtn.click({ timeout: 1500 }).catch(() => {});
        await p.waitForTimeout(1000);
      }
    });
  });

  test('A10: Modules (/modules)', async ({ page }) => {
    await runRoute(page, '10-modules', 'Modules tabs + toggle', '/modules', async (p, tr) => {
      await p.waitForTimeout(1500);
      // Click through 3 tabs: Profiles / Data Packages / System Modules
      for (const label of ['Profiles', 'Data Packages', 'System Modules', 'Profile', 'Data', 'System']) {
        const tab = p.locator(`button:has-text("${label}"), [role="tab"]:has-text("${label}"), a:has-text("${label}")`).first();
        if (await tab.isVisible({ timeout: 800 }).catch(() => false)) {
          await tab.click({ timeout: 1200 }).catch(() => {});
          await p.waitForTimeout(400);
        }
      }

      // Toggle a non-core module
      const toggles = p.locator('[role="switch"], input[type="checkbox"], button[aria-pressed]');
      const n = await toggles.count();
      if (n > 0) {
        try {
          await toggles.nth(Math.min(1, n - 1)).click({ timeout: 1500 });
          await p.waitForTimeout(800);
        } catch { /* ignore */ }
      } else {
        tr.noteUx('No toggles found on modules page');
      }
    });
  });

  test('A11: Validation (/validation)', async ({ page }) => {
    await runRoute(page, '11-validation', 'Validation dashboard', '/validation', async (p, tr) => {
      await p.waitForTimeout(1500);
      const runBtn = p.locator('button:has-text("Run"), button:has-text("Validate"), button:has-text("Check"), button:has-text("Start")').first();
      if (await runBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
        await runBtn.click({ timeout: 1500 }).catch(() => {});
        await p.waitForTimeout(2000);
      } else {
        tr.noteUx('No Run/Validate button on validation page');
      }
    });
  });

  test('A12: AI Estimate (/ai-estimate)', async ({ page }) => {
    await runRoute(page, '12-ai-estimate', 'AI Estimate wizard', '/ai-estimate', async (p, tr) => {
      await p.waitForTimeout(2000);
      const next = p.locator('button:has-text("Next"), button:has-text("Start"), button:has-text("Continue"), button:has-text("Begin")').first();
      if (await next.isVisible({ timeout: 2000 }).catch(() => false)) {
        await next.click({ timeout: 1500 }).catch(() => {});
        await p.waitForTimeout(1500);
      } else {
        tr.noteUx('No wizard start/next button on AI Estimate');
      }
    });
  });

  test('A13: Chat (/chat)', async ({ page }) => {
    await runRoute(page, '13-chat', 'Chat — send message', '/chat', async (p, tr) => {
      await p.waitForTimeout(1500);
      const input = p.locator('textarea, input[type="text"][placeholder*="message" i], input[placeholder*="ask" i], [contenteditable="true"]').last();
      if (await input.isVisible({ timeout: 2000 }).catch(() => false)) {
        await input.fill('Hello audit test').catch(() => {});
        await p.waitForTimeout(300);
        // Send via button or Enter
        const sendBtn = p.locator('button[type="submit"], button:has-text("Send"), button:has(svg)').last();
        if (await sendBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
          await sendBtn.click({ timeout: 1500 }).catch(() => {});
        } else {
          await input.press('Enter').catch(() => {});
        }
        await p.waitForTimeout(2000);
      } else {
        tr.noteUx('No chat input field visible');
      }
    });
  });

  test('A14: Reports (/reports)', async ({ page }) => {
    await runRoute(page, '14-reports', 'Reports — generate/preview', '/reports', async (p, tr) => {
      await p.waitForTimeout(1500);
      const gen = p.locator('button:has-text("Generate"), button:has-text("Preview"), button:has-text("Create"), button:has-text("Export")').first();
      if (await gen.isVisible({ timeout: 2000 }).catch(() => false)) {
        await gen.click({ timeout: 1500 }).catch(() => {});
        await p.waitForTimeout(1500);
      } else {
        tr.noteUx('No Generate/Preview/Export button on reports page');
      }
    });
  });

  test('Z: Write findings summary', async () => {
    // Write machine-readable JSON
    const jsonPath = path.resolve(__dirname, '..', 'test-results', 'audit-findings.json');
    fs.writeFileSync(jsonPath, JSON.stringify(
      { auth: cachedAuth, findings: allFindings, generatedAt: new Date().toISOString() },
      null,
      2,
    ));

    // Write pretty text summary
    const txtPath = path.resolve(__dirname, '..', 'test-results', 'audit-findings.txt');
    const lines: string[] = [];
    lines.push('='.repeat(80));
    lines.push('OpenConstructionERP — Full Journey Audit Findings');
    lines.push(`Generated: ${new Date().toISOString()}`);
    lines.push(`User: ${cachedAuth?.email} (role=${cachedAuth?.role})`);
    lines.push(`New admin-attempt: ${cachedAuth?.newAdminEmail}`);
    lines.push('='.repeat(80));
    for (const f of allFindings) {
      lines.push('');
      lines.push(`── ${f.label} — ${f.route} ${f.ok ? '[OK]' : '[ISSUES]'} (${f.durationMs}ms)`);
      if (f.error) lines.push(`   EXCEPTION: ${f.error}`);
      if (f.httpFailures.length > 0) {
        lines.push(`   HTTP failures (${f.httpFailures.length}):`);
        for (const h of f.httpFailures.slice(0, 20)) {
          lines.push(`     ${h.status} ${h.method} ${h.url}`);
        }
      }
      if (f.consoleErrors.length > 0) {
        lines.push(`   Console errors (${f.consoleErrors.length}):`);
        for (const c of f.consoleErrors.slice(0, 20)) {
          lines.push(`     ${c.text}${c.location ? ` @ ${c.location}` : ''}`);
        }
      }
      if (f.toastErrors.length > 0) {
        lines.push(`   Toast errors (${f.toastErrors.length}):`);
        for (const t of f.toastErrors.slice(0, 10)) {
          lines.push(`     "${t.text}"`);
        }
      }
      if (f.uxIssues.length > 0) {
        lines.push(`   UX issues (${f.uxIssues.length}):`);
        for (const u of f.uxIssues) {
          lines.push(`     - ${u}`);
        }
      }
      if (f.screenshot) lines.push(`   Screenshot: ${f.screenshot}`);
    }
    lines.push('');
    lines.push('='.repeat(80));
    lines.push(`Total routes: ${allFindings.length}, OK: ${allFindings.filter(f => f.ok).length}, With issues: ${allFindings.filter(f => !f.ok).length}`);
    lines.push('='.repeat(80));
    fs.writeFileSync(txtPath, lines.join('\n'));

    console.log('\n' + lines.join('\n'));
    expect(allFindings.length).toBeGreaterThan(10);
  });
});
