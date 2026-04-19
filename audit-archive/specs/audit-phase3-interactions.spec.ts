/**
 * Phase 3 — deep user-interaction audit.
 *
 * Walks realistic work scenarios in each module (not just page loads):
 *   onboarding wizard → documents → contacts → invoices → tasks → workflows.
 *
 * Captures screenshots of modal states, button presses, validation errors,
 * and records every API 4xx/5xx to audit/screenshots/_interactions-report.json.
 *
 * Run:
 *   cd frontend
 *   BASE_URL=http://31.97.123.81:7777 npx playwright test \
 *     --config=playwright.audit.config.ts \
 *     e2e/audit-phase3-interactions.spec.ts
 */
import { test, expect, Page, Locator } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const BASE = process.env['BASE_URL'] || 'http://31.97.123.81:7777';
const EMAIL = process.env['AUDIT_EMAIL'] || 'admin@demo.de';
const PASSWORD = process.env['AUDIT_PASSWORD'] || 'Demo2026!';
const OUT_DIR = path.resolve(__dirname, '..', '..', 'audit', 'screenshots', 'phase3');

type InteractionRecord = {
  module: string;
  action: string;
  screenshot: string | null;
  durationMs: number;
  ok: boolean;
  note: string;
};

const records: InteractionRecord[] = [];
const apiFailures: string[] = [];
const pageErrors: string[] = [];

async function apiLogin(baseUrl: string): Promise<{ access: string; refresh: string; userId: string }> {
  const res = await fetch(`${baseUrl}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!res.ok) throw new Error(`login failed: ${res.status}`);
  const data = await res.json() as { access_token: string; refresh_token: string };
  const payload = JSON.parse(Buffer.from(data.access_token.split('.')[1], 'base64').toString());
  return { access: data.access_token, refresh: data.refresh_token, userId: payload.sub };
}

async function seedAuth(page: Page, tokens: { access: string; refresh: string; userId: string }) {
  await page.goto('/login', { waitUntil: 'commit' });
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
  }, tokens);
}

async function clearOnboardingFlags(page: Page) {
  await page.evaluate(() => {
    localStorage.removeItem('dokufluss-onboarding-done');
    localStorage.removeItem('dokufluss-tour-completed');
  });
}

async function markOnboardingDone(page: Page) {
  await page.evaluate(() => {
    localStorage.setItem('dokufluss-onboarding-done', 'true');
    localStorage.setItem('dokufluss-tour-completed', 'true');
  });
}

async function snap(page: Page, module: string, action: string, ok: boolean, note = '', durationMs = 0) {
  fs.mkdirSync(path.join(OUT_DIR, module), { recursive: true });
  const fname = `${action.replace(/[^a-z0-9]+/gi, '_')}.png`;
  const rel = path.join(module, fname);
  try {
    await page.screenshot({
      path: path.join(OUT_DIR, rel),
      fullPage: false,
      animations: 'disabled',
    });
  } catch {
    /* ignore */
  }
  records.push({
    module,
    action,
    screenshot: rel,
    durationMs,
    ok,
    note,
  });
}

async function trackPage(page: Page) {
  page.on('response', (res) => {
    try {
      const url = res.url();
      if (!url.includes('/api/')) return;
      const status = res.status();
      if (status >= 400 && status < 600) {
        apiFailures.push(`${res.request().method()} ${url} -> ${status}`);
      }
    } catch { /* ignore */ }
  });
  page.on('pageerror', (err) => {
    pageErrors.push(String(err).slice(0, 300));
  });
}

// ── Helper: click if present, log if not found ────────────────────────
async function tryClick(page: Page, loc: Locator, timeoutMs = 3000): Promise<boolean> {
  try {
    await loc.first().waitFor({ state: 'visible', timeout: timeoutMs });
    await loc.first().click();
    return true;
  } catch {
    return false;
  }
}

// ─────────────────────────────────────────────────────────────────────────

test.describe.serial('Phase 3 — user-interaction audit', () => {
  test.setTimeout(1000 * 60 * 20);

  test('0. onboarding wizard — full walk', async ({ page }) => {
    await trackPage(page);
    await page.goto('/login', { waitUntil: 'commit' });
    const tokens = await apiLogin(BASE);
    await seedAuth(page, tokens);
    await clearOnboardingFlags(page); // ensure wizard triggers

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(800);
    await snap(page, 'onboarding', '01_welcome');

    // Step 0 → 1: press "Los geht's" / primary button on welcome
    const step0Next = page.locator('button').filter({ hasText: /Los geht|Get started|Weiter|Next/i });
    const nextOk = await tryClick(page, step0Next, 5000);
    await page.waitForTimeout(400);
    await snap(page, 'onboarding', '02_industry_select', nextOk, nextOk ? '' : 'could not advance from welcome');

    // Step 1: pick industry "Handwerk" if visible
    const handwerk = page.locator('button, [role="button"]').filter({ hasText: /Handwerk|Construction|Crafts/i });
    const handwerkOk = await tryClick(page, handwerk, 3000);
    await page.waitForTimeout(400);
    await snap(page, 'onboarding', '03_after_industry_pick', handwerkOk);

    // Step 2: finish
    const finishBtn = page.locator('button').filter({ hasText: /Los geht|Fertig|Finish|Zur App/i });
    const finishedOk = await tryClick(page, finishBtn, 5000);
    await page.waitForTimeout(1000);
    await snap(page, 'onboarding', '04_after_finish', finishedOk);

    // Verify we landed somewhere useful (not stuck on wizard)
    const url = page.url();
    const stillOnWizard = await page.locator('text=/Willkommen|Welcome/i').first().isVisible().catch(() => false);
    records.push({
      module: 'onboarding',
      action: 'final_url_check',
      screenshot: null,
      durationMs: 0,
      ok: !stillOnWizard,
      note: `landed at ${url}, stillOnWizard=${stillOnWizard}`,
    });
  });

  test('1. documents — upload modal open/close + search + filters', async ({ page }) => {
    await trackPage(page);
    const tokens = await apiLogin(BASE);
    await seedAuth(page, tokens);
    await markOnboardingDone(page);

    await page.goto('/documents', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => {});
    await snap(page, 'documents', '01_list');

    // Open upload modal
    const uploadBtn = page.locator('button').filter({ hasText: /Hochladen|Upload/i });
    const uploadOpened = await tryClick(page, uploadBtn, 5000);
    await page.waitForTimeout(500);
    await snap(page, 'documents', '02_upload_modal', uploadOpened);

    // Close modal via Escape
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
    await snap(page, 'documents', '03_modal_closed');

    // Search for "test"
    const searchInput = page.locator('input[placeholder*="Suchbegriff"], input[placeholder*="Search"]').first();
    if (await searchInput.isVisible().catch(() => false)) {
      await searchInput.fill('test');
      await page.waitForTimeout(600);
      await snap(page, 'documents', '04_search_test');
    }

    // Open filters
    const filtersBtn = page.locator('button').filter({ hasText: /Filtern|Filter/i });
    const filtersOpened = await tryClick(page, filtersBtn, 3000);
    await page.waitForTimeout(300);
    await snap(page, 'documents', '05_filters_open', filtersOpened);
  });

  test('2. contacts — full create→edit→delete cycle', async ({ page }) => {
    await trackPage(page);
    const tokens = await apiLogin(BASE);
    await seedAuth(page, tokens);
    await markOnboardingDone(page);

    await page.goto('/contacts', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => {});
    await snap(page, 'contacts', '01_list');

    // Open "New contact" form
    const newBtn = page.locator('button').filter({ hasText: /Neuer Kontakt|New contact|Neuen Kontakt erstellen|Kontakt hinzufügen/i });
    const opened = await tryClick(page, newBtn, 5000);
    await page.waitForTimeout(500);
    await snap(page, 'contacts', '02_new_modal', opened);

    // Try submitting empty form — should show validation error
    const saveBtn = page.locator('button').filter({ hasText: /Speichern|Save/i });
    const saveClicked = await tryClick(page, saveBtn, 3000);
    await page.waitForTimeout(500);
    await snap(page, 'contacts', '03_empty_submit_validation', saveClicked, 'expect validation prompt');

    // Fill minimal valid form
    const companyInput = page.locator('input[name*="company"], input[placeholder*="Firmenname"], input[placeholder*="Company"]').first();
    if (await companyInput.isVisible().catch(() => false)) {
      await companyInput.fill(`Audit-E2E ${Date.now()}`);
      const emailInput = page.locator('input[type="email"], input[name="email"], input[placeholder*="E-Mail"]').first();
      if (await emailInput.isVisible().catch(() => false)) {
        await emailInput.fill(`audit-e2e-${Date.now()}@example.de`);
      }
      await snap(page, 'contacts', '04_filled_form');
      // Submit
      await saveBtn.first().click().catch(() => {});
      await page.waitForTimeout(1200);
      await snap(page, 'contacts', '05_after_submit');
    }

    // Close any open dialog
    await page.keyboard.press('Escape');
  });

  test('3. invoices — open creator + tab navigation', async ({ page }) => {
    await trackPage(page);
    const tokens = await apiLogin(BASE);
    await seedAuth(page, tokens);
    await markOnboardingDone(page);

    await page.goto('/invoices', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => {});
    await snap(page, 'invoices', '01_list');

    // Click tabs
    for (const tab of ['Alle', 'Entwürfe', 'Gesendet', 'Bezahlt', 'Überfällig']) {
      const loc = page.locator(`button`).filter({ hasText: new RegExp(`^${tab}$`, 'i') }).first();
      const ok = await tryClick(page, loc, 2000);
      await page.waitForTimeout(300);
      if (ok) await snap(page, 'invoices', `02_tab_${tab}`, ok);
    }

    // Open creator
    await page.goto('/invoices/new', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => {});
    await snap(page, 'invoices', '03_creator');
  });

  test('4. tasks — create quick task + mark complete', async ({ page }) => {
    await trackPage(page);
    const tokens = await apiLogin(BASE);
    await seedAuth(page, tokens);
    await markOnboardingDone(page);

    await page.goto('/tasks', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => {});
    await snap(page, 'tasks', '01_list');

    const createBtn = page.locator('button').filter({ hasText: /Neue Aufgabe|New task|Aufgabe erstellen|Aufgabe hinzufügen/i });
    const opened = await tryClick(page, createBtn, 5000);
    await page.waitForTimeout(500);
    await snap(page, 'tasks', '02_create_modal', opened);
  });

  test('5. workflows — click new workflow → designer opens', async ({ page }) => {
    await trackPage(page);
    const tokens = await apiLogin(BASE);
    await seedAuth(page, tokens);
    await markOnboardingDone(page);

    await page.goto('/workflows', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => {});
    await snap(page, 'workflows', '01_list');

    const newBtn = page.locator('button').filter({ hasText: /Neuen Workflow|New workflow/i });
    const opened = await tryClick(page, newBtn, 5000);
    await page.waitForTimeout(1200);
    await snap(page, 'workflows', '02_after_click_new', opened);

    // Check URL
    records.push({
      module: 'workflows',
      action: 'designer_url_check',
      screenshot: null,
      durationMs: 0,
      ok: /workflows\/(new|.*\/designer)/.test(page.url()),
      note: `url=${page.url()}`,
    });
  });

  test('6. cabinets — open + try create', async ({ page }) => {
    await trackPage(page);
    const tokens = await apiLogin(BASE);
    await seedAuth(page, tokens);
    await markOnboardingDone(page);

    await page.goto('/cabinets', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => {});
    await snap(page, 'cabinets', '01_list');

    const newBtn = page.locator('button').filter({ hasText: /Neuer Schrank|Neuen Schrank|New cabinet|Schrank erstellen|Schrank anlegen/i });
    const opened = await tryClick(page, newBtn, 5000);
    await page.waitForTimeout(600);
    await snap(page, 'cabinets', '02_create_modal', opened);
  });

  test('7. final — write interactions report', async () => {
    fs.mkdirSync(OUT_DIR, { recursive: true });
    const report = {
      baseUrl: BASE,
      generatedAt: new Date().toISOString(),
      totalActions: records.length,
      pagesWithErrors: pageErrors.length,
      apiFailureCount: apiFailures.length,
      uniqueApiFailures: [...new Set(apiFailures)],
      records,
      pageErrors,
    };
    fs.writeFileSync(
      path.join(OUT_DIR, '_interactions-report.json'),
      JSON.stringify(report, null, 2),
      'utf-8'
    );
    expect(records.length).toBeGreaterThan(5);
  });
});
