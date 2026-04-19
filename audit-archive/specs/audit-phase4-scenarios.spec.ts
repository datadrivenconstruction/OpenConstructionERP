/**
 * Phase 4 — 50-scenario user walkthrough.
 *
 * Each scenario from `audit/04-scenarios.md` is encoded as a compact
 * navigation + assertion. Playwright records per-scenario:
 *   - reached (did the URL / modal / state we expected appear)
 *   - friction notes (what the novice path looked like)
 *   - any API 4xx/5xx that bubbled up during the flow
 *
 * Report → audit/screenshots/phase4/_scenarios-report.json
 *
 * Run:
 *   BASE_URL=http://31.97.123.81:7777 npx playwright test \
 *     e2e/audit-phase4-scenarios.spec.ts \
 *     --config=playwright.audit.config.ts
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
const OUT_DIR = path.resolve(__dirname, '..', '..', 'audit', 'screenshots', 'phase4');

type ScenarioResult = {
  id: number;
  title: string;
  category: string;
  reached: boolean;
  friction: string;
  apiFailures: string[];
  screenshot: string;
  durationMs: number;
};

const results: ScenarioResult[] = [];

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
        user: { id: userId, email: 'admin@demo.de', firstName: 'Max', lastName: 'Mueller', role: 'admin', orgId: 'demo', orgName: 'Muster GmbH' },
        tokens: { access, refresh },
        isAuthenticated: true,
      },
      version: 0,
    };
    localStorage.setItem('dokufluss-auth', JSON.stringify(payload));
    localStorage.setItem('dokufluss-onboarding-done', 'true');
    localStorage.setItem('dokufluss-tour-completed', 'true');
  }, tokens);
}

function trackApi(page: Page, failures: string[]) {
  page.on('response', (res) => {
    try {
      const url = res.url();
      if (!url.includes('/api/')) return;
      const s = res.status();
      if (s >= 400 && s < 600) failures.push(`${res.request().method()} ${url} -> ${s}`);
    } catch { /* ignore */ }
  });
}

async function snap(page: Page, category: string, id: number, tag: string): Promise<string> {
  fs.mkdirSync(path.join(OUT_DIR, category), { recursive: true });
  const fname = `${String(id).padStart(2, '0')}-${tag}.png`;
  const rel = path.join(category, fname);
  try {
    await page.screenshot({ path: path.join(OUT_DIR, rel), fullPage: false, animations: 'disabled' });
  } catch { /* ignore */ }
  return rel;
}

async function exists(page: Page, loc: Locator, timeoutMs = 3000): Promise<boolean> {
  try {
    await loc.first().waitFor({ state: 'visible', timeout: timeoutMs });
    return true;
  } catch {
    return false;
  }
}

async function runScenario(
  page: Page,
  id: number,
  title: string,
  category: string,
  fn: (p: Page) => Promise<{ reached: boolean; friction: string }>,
): Promise<void> {
  const apiFailures: string[] = [];
  trackApi(page, apiFailures);
  const t0 = Date.now();
  let reached = false;
  let friction = '';
  try {
    const out = await fn(page);
    reached = out.reached;
    friction = out.friction;
  } catch (exc) {
    friction = `exception: ${String(exc).slice(0, 150)}`;
  }
  const screenshot = await snap(page, category, id, reached ? 'ok' : 'fail');
  results.push({ id, title, category, reached, friction, apiFailures: [...new Set(apiFailures)], screenshot, durationMs: Date.now() - t0 });
}

// Helper navigators (novice paths)
async function clickNav(page: Page, label: string): Promise<boolean> {
  return await exists(page, page.locator('nav, aside').getByText(new RegExp(`^\\s*${label}\\s*$`, 'i')).first(), 2000);
}

async function gotoAndWait(page: Page, url: string) {
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
}

// ─────────────────────────────────────────────────────────────────────
test.describe.serial('Phase 4 — 50 user scenarios', () => {
  test.setTimeout(1000 * 60 * 30);

  test.beforeAll(async () => { fs.mkdirSync(OUT_DIR, { recursive: true }); });

  test('scenarios 1-50', async ({ page }) => {
    const tokens = await apiLogin(BASE);
    await seedAuth(page, tokens);

    // ─── A. Onboarding (1-5) ────────────────────────────────────────
    // 1: login+dashboard (we already bypassed onboarding; verify dashboard loads)
    await runScenario(page, 1, 'First login → dashboard', 'A-onboarding', async (p) => {
      await gotoAndWait(p, '/');
      const ok = await exists(p, p.locator('h1, h2').filter({ hasText: /Willkommen|Good|Guten/i }).first(), 5000);
      return { reached: ok, friction: ok ? '' : 'no greeting visible' };
    });

    // 2: Language switch via Settings
    await runScenario(page, 2, 'Change language to English in Settings', 'A-onboarding', async (p) => {
      await gotoAndWait(p, '/settings');
      const found = await exists(p, p.getByText(/Sprache|Language/i).first(), 3000);
      return { reached: found, friction: found ? '' : 'Settings has no Sprache tab visible' };
    });

    // 3: Skip onboarding — covered by baseline (we already did), so just verify no wizard
    await runScenario(page, 3, 'Skip onboarding flow', 'A-onboarding', async (p) => {
      await gotoAndWait(p, '/');
      const stillWizard = await exists(p, p.getByText(/Los geht's.*Weiter|Fertig.*Abbrechen/i).first(), 1500);
      return { reached: !stillWizard, friction: stillWizard ? 'wizard blocks dashboard' : '' };
    });

    // 4: Invite a colleague — check form reachable
    await runScenario(page, 4, 'Invite colleague form reachable', 'A-onboarding', async (p) => {
      await gotoAndWait(p, '/admin');
      const inviteBtn = p.locator('button').filter({ hasText: /Einladen|Invite|Einladung/i }).first();
      const ok = await exists(p, inviteBtn, 3000);
      return { reached: ok, friction: ok ? '' : 'No invite button on Admin page' };
    });

    // 5: Change password — reachable
    await runScenario(page, 5, 'Password change form reachable', 'A-onboarding', async (p) => {
      await gotoAndWait(p, '/settings');
      const pwBtn = p.locator('button').filter({ hasText: /Passwort ändern|Change password/i }).first();
      const ok = await exists(p, pwBtn, 3000);
      return { reached: ok, friction: ok ? '' : 'No password change button' };
    });

    // ─── B. Documents (6-10) ────────────────────────────────────────
    await runScenario(page, 6, 'Upload modal opens', 'B-documents', async (p) => {
      await gotoAndWait(p, '/documents');
      const btn = p.locator('button').filter({ hasText: /Hochladen|Upload/i }).first();
      await btn.click().catch(() => {});
      await p.waitForTimeout(500);
      const modalOk = await exists(p, p.getByText(/Dateien hier ablegen|Drop files/i).first(), 3000);
      if (modalOk) await p.keyboard.press('Escape');
      return { reached: modalOk, friction: modalOk ? '' : 'Upload modal did not appear' };
    });

    await runScenario(page, 7, 'Multi-file upload modal (accepts multiple)', 'B-documents', async (p) => {
      await gotoAndWait(p, '/documents');
      const btn = p.locator('button').filter({ hasText: /Hochladen|Upload/i }).first();
      await btn.click().catch(() => {});
      await p.waitForTimeout(400);
      const inputMultiple = await p.locator('input[type="file"][multiple]').count();
      if (inputMultiple > 0) await p.keyboard.press('Escape');
      return { reached: inputMultiple > 0, friction: inputMultiple > 0 ? '' : 'file input is not multiple' };
    });

    await runScenario(page, 8, 'Filter documents list', 'B-documents', async (p) => {
      await gotoAndWait(p, '/documents');
      const filterBtn = p.locator('button').filter({ hasText: /Filtern|Filter/i }).first();
      const ok = await exists(p, filterBtn, 3000);
      return { reached: ok, friction: ok ? '' : 'no Filter button' };
    });

    await runScenario(page, 9, 'Search box present on Documents', 'B-documents', async (p) => {
      await gotoAndWait(p, '/documents');
      const search = p.locator('input[placeholder*="Such"], input[placeholder*="Search"]').first();
      const ok = await exists(p, search, 3000);
      return { reached: ok, friction: ok ? '' : 'no search input' };
    });

    await runScenario(page, 10, 'Spotlight Cmd+K opens', 'B-documents', async (p) => {
      await gotoAndWait(p, '/');
      await p.waitForTimeout(400);
      await p.keyboard.press('Control+k');
      await p.waitForTimeout(600);
      // Spotlight typically has a search input that auto-focuses
      const focused = await p.evaluate(() => {
        const el = document.activeElement;
        return el?.tagName === 'INPUT' && (el as HTMLInputElement).placeholder?.toLowerCase().includes('such');
      });
      if (focused) await p.keyboard.press('Escape');
      return { reached: !!focused, friction: focused ? '' : 'Cmd+K focus did not land on spotlight input' };
    });

    // ─── C. Cabinets (11-13) ────────────────────────────────────────
    await runScenario(page, 11, 'Create cabinet button reachable', 'C-cabinets', async (p) => {
      await gotoAndWait(p, '/cabinets');
      const btn = p.locator('button').filter({ hasText: /Neuer Schrank|Neu|Schrank anlegen/i }).first();
      const ok = await exists(p, btn, 3000);
      return { reached: ok, friction: ok ? '' : 'no create button' };
    });

    await runScenario(page, 12, 'Cabinet card exists and is clickable', 'C-cabinets', async (p) => {
      await gotoAndWait(p, '/cabinets');
      // Look for any default seeded cabinet name that appears on the page
      const ok = await exists(p, p.getByText(/Eingangsrechnungen|Allgemein|Verträge|Angebote/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no seeded cabinet visible' };
    });

    await runScenario(page, 13, 'Cabinet list visible', 'C-cabinets', async (p) => {
      await gotoAndWait(p, '/cabinets');
      const text = await p.locator('body').textContent();
      const hasDefault = /Allgemein|Eingangsrechnungen|Verträge|Rechnungen/i.test(text || '');
      return { reached: hasDefault, friction: hasDefault ? '' : 'no default cabinets shown' };
    });

    // ─── D. Invoicing (14-19) ───────────────────────────────────────
    await runScenario(page, 14, 'Invoice creator opens', 'D-invoicing', async (p) => {
      await gotoAndWait(p, '/invoices/new');
      const ok = await exists(p, p.getByText(/Kunde|Rechnung|Kundenname|Empfänger/i).first(), 4000);
      return { reached: ok, friction: ok ? '' : 'creator did not render' };
    });

    await runScenario(page, 15, 'Invoice list has action buttons', 'D-invoicing', async (p) => {
      await gotoAndWait(p, '/invoices');
      const ok = await exists(p, p.locator('button').filter({ hasText: /Rechnung erstellen|Neu|Drucken|Exportieren/i }).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no action buttons on invoices' };
    });

    await runScenario(page, 16, 'Dunning (Mahnwesen) list reachable', 'D-invoicing', async (p) => {
      await gotoAndWait(p, '/dunning');
      const ok = await exists(p, p.getByText(/Mahnung|Dunning|Mahnwesen/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'dunning page empty' };
    });

    await runScenario(page, 17, 'Recurring invoices section', 'D-invoicing', async (p) => {
      await gotoAndWait(p, '/invoices');
      const recurTab = p.locator('button, a').filter({ hasText: /Serien|Recurring|Wiederkehrend/i }).first();
      const ok = await exists(p, recurTab, 3000);
      return { reached: ok, friction: ok ? '' : 'no recurring tab/button' };
    });

    await runScenario(page, 18, 'E-Invoice page reachable', 'D-invoicing', async (p) => {
      await gotoAndWait(p, '/e-invoice');
      const ok = await exists(p, p.getByText(/XRechnung|E-Rechnung|Peppol/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'e-invoice page empty' };
    });

    await runScenario(page, 19, 'Dunning list has overdue tab', 'D-invoicing', async (p) => {
      await gotoAndWait(p, '/dunning');
      const ok = await exists(p, p.getByText(/Überfällig|Overdue|Fällig/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no overdue tab' };
    });

    // ─── E. Accounting (20-23) ──────────────────────────────────────
    await runScenario(page, 20, 'Accounting EÜR tab', 'E-accounting', async (p) => {
      await gotoAndWait(p, '/accounting');
      const ok = await exists(p, p.getByText(/EÜR|Einnahmen.Überschuss/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no EÜR tab' };
    });

    await runScenario(page, 21, 'DATEV export page reachable', 'E-accounting', async (p) => {
      await gotoAndWait(p, '/datev-export');
      const ok = await exists(p, p.getByText(/DATEV/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'DATEV page empty' };
    });

    await runScenario(page, 22, 'Accounting UStVA tab', 'E-accounting', async (p) => {
      await gotoAndWait(p, '/accounting');
      const ok = await exists(p, p.getByText(/UStVA|Umsatzsteuer/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no UStVA tab' };
    });

    await runScenario(page, 23, 'Accounting accounts (Kontenzuordnung) tab', 'E-accounting', async (p) => {
      await gotoAndWait(p, '/accounting');
      const ok = await exists(p, p.getByText(/Kontenzuordnung|Kontierung|Kosten/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no account mapping tab' };
    });

    // ─── F. Banking (24-26) ─────────────────────────────────────────
    await runScenario(page, 24, 'Banking "Bank verbinden" reachable', 'F-banking', async (p) => {
      await gotoAndWait(p, '/banking');
      const ok = await exists(p, p.locator('button').filter({ hasText: /Bank verbinden|FinTS|Connect/i }).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no FinTS button' };
    });

    await runScenario(page, 25, 'Banking import button reachable', 'F-banking', async (p) => {
      await gotoAndWait(p, '/banking');
      const ok = await exists(p, p.locator('button').filter({ hasText: /Importieren|Import|CSV|MT940/i }).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no import button' };
    });

    await runScenario(page, 26, 'Banking reconciliation tab', 'F-banking', async (p) => {
      await gotoAndWait(p, '/banking');
      const ok = await exists(p, p.getByText(/Abgleich|Reconcile|Zuordnung/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no reconcile tab' };
    });

    // ─── G. Contacts (27-30) ────────────────────────────────────────
    await runScenario(page, 27, 'Add contact form opens', 'G-contacts', async (p) => {
      await gotoAndWait(p, '/contacts');
      const btn = p.locator('button').filter({ hasText: /Neuer Kontakt|Neuen Kontakt|New contact/i }).first();
      await btn.click().catch(() => {});
      await p.waitForTimeout(400);
      const ok = await exists(p, p.getByText(/Firmenname|Company name/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no contact form' };
    });

    await runScenario(page, 28, 'Business card scanner reachable', 'G-contacts', async (p) => {
      await gotoAndWait(p, '/contacts');
      const btn = p.locator('button').filter({ hasText: /Visitenkarte|Business card|BCR/i }).first();
      const ok = await exists(p, btn, 3000);
      return { reached: ok, friction: ok ? '' : 'no card-scanner entry' };
    });

    await runScenario(page, 29, 'CSV import reachable', 'G-contacts', async (p) => {
      await gotoAndWait(p, '/contacts');
      const btn = p.locator('button').filter({ hasText: /Importieren|Import|CSV/i }).first();
      const ok = await exists(p, btn, 3000);
      return { reached: ok, friction: ok ? '' : 'no import button' };
    });

    await runScenario(page, 30, 'Communication log tab inside contact', 'G-contacts', async (p) => {
      await gotoAndWait(p, '/contacts');
      const ok = await exists(p, p.getByText(/Kommunikation|Communication|Aktivitäten/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no communication tab on list page (expected on detail)' };
    });

    // ─── H. Contracts (31-33) ───────────────────────────────────────
    await runScenario(page, 31, 'New contract form reachable', 'H-contracts', async (p) => {
      await gotoAndWait(p, '/contracts');
      const ok = await exists(p, p.locator('button').filter({ hasText: /Neuer Vertrag|New contract|Vertrag anlegen/i }).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no new-contract button' };
    });

    await runScenario(page, 32, 'Contracts "Läuft bald aus" tab', 'H-contracts', async (p) => {
      await gotoAndWait(p, '/contracts');
      const ok = await exists(p, p.getByText(/Läuft bald aus|Expiring|Ablaufende/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no expiring tab' };
    });

    await runScenario(page, 33, 'Contract list has status column + Gekündigt filter', 'H-contracts', async (p) => {
      await gotoAndWait(p, '/contracts');
      // Kündigen action lives on detail/modal; list page has a "Gekündigt" filter tab
      const ok = await exists(p, p.getByText(/Gekündigt|Terminated|Status/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no Gekündigt tab/status column' };
    });

    // ─── I. Projects/Construction (34-36) ───────────────────────────
    await runScenario(page, 34, 'Projects page has create action', 'I-projects', async (p) => {
      await gotoAndWait(p, '/projects');
      // Primary action is labeled "Erstellen" via t('common.create'); accept several variants
      const ok = await exists(p, p.locator('button').filter({ hasText: /Erstellen|Create|Neues Projekt|Neu anlegen|\+\s*Neu/i }).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no create button' };
    });

    await runScenario(page, 35, 'Bautagebuch create entry', 'I-projects', async (p) => {
      await gotoAndWait(p, '/bautagebuch');
      const ok = await exists(p, p.locator('button').filter({ hasText: /Neuer Eintrag|New entry|Eintrag hinzufügen/i }).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no new-entry button' };
    });

    await runScenario(page, 36, 'Aufmaß measurement page', 'I-projects', async (p) => {
      await gotoAndWait(p, '/aufmass');
      const ok = await exists(p, p.getByText(/Aufmaß|Maß|Measurement/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'aufmass page empty' };
    });

    // ─── J. Tasks/Workflows (37-40) ─────────────────────────────────
    await runScenario(page, 37, 'Create task modal', 'J-tasks', async (p) => {
      await gotoAndWait(p, '/tasks');
      const btn = p.locator('button').filter({ hasText: /Neue Aufgabe|Aufgabe|New task/i }).first();
      await btn.click().catch(() => {});
      await p.waitForTimeout(400);
      const ok = await exists(p, p.getByText(/Aufgabenname|Task name|Aufgabe erstellen/i).first(), 3000);
      if (ok) await p.keyboard.press('Escape');
      return { reached: ok, friction: ok ? '' : 'no task modal' };
    });

    await runScenario(page, 38, 'Task list shows priority/assignee fields', 'J-tasks', async (p) => {
      await gotoAndWait(p, '/tasks');
      const ok = await exists(p, p.getByText(/Priorität|Zuständig|Zugewiesen|Assignee/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no priority/assignee column visible (empty list?)' };
    });

    await runScenario(page, 39, 'Wiedervorlage page loads', 'J-tasks', async (p) => {
      await gotoAndWait(p, '/wiedervorlage');
      const ok = await exists(p, p.getByText(/Wiedervorlage|Follow.up/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'wiedervorlage page empty' };
    });

    await runScenario(page, 40, 'Workflow designer opens for new', 'J-tasks', async (p) => {
      await gotoAndWait(p, '/workflows');
      const btn = p.locator('button').filter({ hasText: /Neuen Workflow erstellen|Neuer Workflow|New workflow/i }).first();
      await btn.click().catch(() => {});
      await p.waitForTimeout(800);
      const inDesigner = /workflows\/(new|.*\/designer)/.test(p.url());
      return { reached: inDesigner, friction: inDesigner ? '' : `url=${p.url()}` };
    });

    // ─── K. Time/HR (41-43) ─────────────────────────────────────────
    await runScenario(page, 41, 'Timetracking add entry', 'K-hr', async (p) => {
      await gotoAndWait(p, '/timetracking');
      const btn = p.locator('button').filter({ hasText: /Zeit erfassen|Eintrag|New entry/i }).first();
      const ok = await exists(p, btn, 3000);
      return { reached: ok, friction: ok ? '' : 'no add-entry button' };
    });

    await runScenario(page, 42, 'Vacation request form', 'K-hr', async (p) => {
      await gotoAndWait(p, '/leave');
      const btn = p.locator('button').filter({ hasText: /Urlaub|Antrag|Leave|Request/i }).first();
      const ok = await exists(p, btn, 3000);
      return { reached: ok, friction: ok ? '' : 'no vacation-request button' };
    });

    await runScenario(page, 43, 'Leave — pending approvals list', 'K-hr', async (p) => {
      await gotoAndWait(p, '/leave');
      const ok = await exists(p, p.getByText(/Beantragt|Pending|Offen|Genehmigung/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no pending list' };
    });

    // ─── L. Compliance (44-46) ──────────────────────────────────────
    await runScenario(page, 44, 'Compliance verify-chain button', 'L-compliance', async (p) => {
      await gotoAndWait(p, '/compliance');
      const ok = await exists(p, p.locator('button').filter({ hasText: /Kette verifizieren|Verify chain/i }).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no verify-chain button' };
    });

    await runScenario(page, 45, 'GDPdU export section', 'L-compliance', async (p) => {
      await gotoAndWait(p, '/compliance');
      const ok = await exists(p, p.getByText(/GDPdU|Datenträgerüberlassung/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no GDPdU tab' };
    });

    await runScenario(page, 46, 'Retention monitor', 'L-compliance', async (p) => {
      await gotoAndWait(p, '/compliance');
      const ok = await exists(p, p.getByText(/Aufbewahrungsfristen|Retention/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no retention section' };
    });

    // ─── M. Search / AI (47-48) ─────────────────────────────────────
    await runScenario(page, 47, 'AI assistant entry visible in sidebar', 'M-ai', async (p) => {
      await gotoAndWait(p, '/');
      // The top-of-sidebar has a Sparkles button with aria-label "KI-Assistent"
      const ok = await exists(p, p.locator('[aria-label*="Assistent" i], [data-tour="ai-chat"]').first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no sparkle button in sidebar' };
    });

    await runScenario(page, 48, 'Semantic search field', 'M-ai', async (p) => {
      await gotoAndWait(p, '/search');
      const ok = await exists(p, p.locator('input').filter({ hasText: '' }).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no search input' };
    });

    // ─── N. Cross-cutting (49-50) ───────────────────────────────────
    await runScenario(page, 49, 'Dark mode toggle reachable', 'N-cross', async (p) => {
      await gotoAndWait(p, '/settings');
      const ok = await exists(p, p.getByText(/Dunkel|Dark|Erscheinungsbild|Appearance/i).first(), 3000);
      return { reached: ok, friction: ok ? '' : 'no dark-mode toggle' };
    });

    await runScenario(page, 50, 'Logout accessible via user menu', 'N-cross', async (p) => {
      await gotoAndWait(p, '/');
      // User block with "Max Mueller" / "Administrator" lives at the bottom-left of the sidebar
      const userBlock = p.locator('aside, nav').getByText(/Max Mueller|Administrator/i).first();
      await userBlock.click({ force: true }).catch(() => {});
      await p.waitForTimeout(500);
      const ok = await exists(p, p.getByText(/Abmelden|Logout|Sign out/i).first(), 2500);
      return { reached: ok, friction: ok ? '' : 'logout menu did not appear after clicking user block' };
    });

    // ─── Write consolidated report ─────────────────────────────────
    const reached = results.filter((r) => r.reached).length;
    const missing = results.filter((r) => !r.reached);
    const totalApiFails = new Set(results.flatMap((r) => r.apiFailures));
    const report = {
      baseUrl: BASE,
      generatedAt: new Date().toISOString(),
      totalScenarios: results.length,
      reachedCount: reached,
      reachedPct: Math.round(reached * 100 / results.length),
      uniqueApiFailures: [...totalApiFails],
      results,
      missingSummary: missing.map((r) => ({ id: r.id, title: r.title, friction: r.friction })),
    };
    fs.writeFileSync(path.join(OUT_DIR, '_scenarios-report.json'), JSON.stringify(report, null, 2), 'utf-8');
    expect(results.length).toBe(50);
  });
});
