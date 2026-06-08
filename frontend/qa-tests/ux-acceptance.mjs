// UX acceptance harness - deep, multi-pass, real-click + screenshot verification.
//
// The founder's bar: every module must be clear and usable, fully translated in
// all 27 locales, and signed off only after thorough testing through real clicks,
// screenshots, and screenshot analysis - 3 to 4 genuinely deep passes, not one
// shallow smoke test. This script encodes that as a reusable acceptance gate.
//
// It logs in through the REAL demo UI (token injection is rejected by the API),
// then runs four passes per module:
//   PASS 1  SMOKE      navigate, screenshot, collect console + page errors,
//                      assert no redirect to /login and no error-boundary crash.
//   PASS 2  INTERACT   real, non-destructive clicks on the core affordances
//                      (help/info, empty-state CTA, first panel/drawer opener),
//                      screenshot each resulting state.
//   PASS 3  I18N       reload under a representative locale set (LTR, RTL, CJK,
//                      plus the lowest-coverage locales), screenshot, and scan
//                      the visible DOM for raw-key leaks and English-equal leaks.
//   PASS 4  GUIDANCE   detect which of the 8 in-product-guidance standard items
//                      are present (intro/empty-state, field help, first-run tour,
//                      explanatory errors, AI reason+confidence, presets,
//                      progressive disclosure, consistency markers).
//
// Screenshots land in qa-tests/ux-acceptance/<module>/passN[_locale].png so they
// can be read back and analysed visually. A machine report is written to
// qa-tests/ux-acceptance/report.json.
//
// Usage:
//   node qa-tests/ux-acceptance.mjs all
//   node qa-tests/ux-acceptance.mjs boq,costs,validation --locales de,ru,ja,ar
//   BASE=http://localhost:4173 node qa-tests/ux-acceptance.mjs all   (preview/built)
//
// Default BASE is the dev server. For perf-sensitive judgement use a built
// preview, but for functional/clarity/i18n verification the dev server is fine.

import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const BASE = process.env.BASE || 'http://localhost:5173';
const OUTROOT = join(__dirname, 'ux-acceptance');
const DEMO_EMAIL = 'demo@openconstructionerp.com';

// Representative locale set: English baseline, the lowest-coverage locales
// (nl/fr), a Cyrillic, a CJK trio, and the RTL case. Override with --locales.
const DEFAULT_LOCALES = ['de', 'fr', 'nl', 'ru', 'zh', 'ja', 'ar'];

// Module registry. route is the deep link; interactions are SAFE, non-destructive
// click targets tried in order (each wrapped in try/catch). Extend per wave.
const MODULES = {
  boq: { label: 'Bill of Quantities', route: '/boq' },
  costs: { label: 'Cost database', route: '/costs' },
  validation: { label: 'Validation', route: '/validation' },
  projects: { label: 'Projects', route: '/projects' },
  takeoff: { label: 'Takeoff', route: '/takeoff' },
  bim: { label: 'BIM viewer', route: '/bim' },
  geo: { label: 'Geo Hub', route: '/geo' },
  'data-explorer': { label: 'Data Explorer', route: '/data-explorer' },
  'ai-estimator': { label: 'AI Estimator', route: '/ai-estimator' },
  'match-elements': { label: 'Match elements', route: '/match-elements' },
  scheduling: { label: 'Scheduling', route: '/scheduling' },
  contracts: { label: 'Contracts', route: '/contracts' },
  procurement: { label: 'Procurement', route: '/procurement' },
  rfi: { label: 'RFIs', route: '/rfi' },
  submittals: { label: 'Submittals', route: '/submittals' },
  'daily-diary': { label: 'Daily Diary', route: '/daily-diary' },
  inspections: { label: 'Inspections', route: '/inspections' },
  hse: { label: 'Safety / HSE', route: '/hse' },
  files: { label: 'File manager', route: '/files' },
  reports: { label: 'Reports', route: '/reports' },
  analytics: { label: 'Analytics', route: '/analytics' },
  finance: { label: 'Finance', route: '/finance' },
  dashboard: { label: 'Dashboard', route: '/dashboard' },
};

function parseArgs() {
  const [, , target = 'all', ...rest] = process.argv;
  let locales = DEFAULT_LOCALES;
  const li = rest.indexOf('--locales');
  if (li >= 0 && rest[li + 1]) locales = rest[li + 1].split(',').map((s) => s.trim()).filter(Boolean);
  const keys = target === 'all' ? Object.keys(MODULES) : target.split(',').map((s) => s.trim());
  return { keys, locales };
}

async function login(page) {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
  const demoBtn = page.locator('button').filter({ hasText: DEMO_EMAIL }).first();
  if (!(await demoBtn.isVisible().catch(() => false))) {
    const tryDemo = page.getByRole('button', { name: /try demo|demo/i }).first();
    if (await tryDemo.isVisible().catch(() => false)) await tryDemo.click();
    await demoBtn.waitFor({ state: 'visible', timeout: 12000 }).catch(() => {});
  }
  await demoBtn.click().catch(() => {});
  await page.waitForURL(/\/(dashboard|projects|$)/, { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1500);
  if (/\/login/.test(page.url())) throw new Error('login did not navigate away from /login');
}

// Scan visible text for raw key leaks and obvious untranslated-English leaks.
async function scanI18n(page, locale) {
  return page.evaluate(
    ({ locale }) => {
      const keyish = (s) => /^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$/.test(s);
      const out = { rawKeys: [], suspectEnglish: [], sampleCount: 0 };
      const cjkOrRtl = ['zh', 'ja', 'ko', 'ar', 'ru', 'th', 'hi', 'bg'].includes(locale);
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let n;
      while ((n = walker.nextNode())) {
        const t = (n.textContent || '').trim();
        if (!t || t.length < 2) continue;
        const el = n.parentElement;
        if (!el) continue;
        const tag = el.tagName;
        if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'CODE' || tag === 'PRE') continue;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        out.sampleCount++;
        // Raw key leak: the whole visible token looks like an i18n key.
        for (const tok of t.split(/\s+/)) {
          if (keyish(tok)) { out.rawKeys.push(tok); break; }
        }
        // English-equal leak heuristic: on a non-Latin-script locale, a long
        // run of plain ASCII letters in a heading/label is likely untranslated.
        if (cjkOrRtl && /^[\x20-\x7E]+$/.test(t) && /[A-Za-z]{4,}/.test(t)) {
          // ignore numbers, codes, currency, units, proper nouns under 1 word
          const words = t.split(/\s+/).filter((w) => /[A-Za-z]{3,}/.test(w));
          if (words.length >= 2 && (tag === 'H1' || tag === 'H2' || tag === 'H3' || tag === 'BUTTON' || tag === 'LABEL' || tag === 'A' || el.getAttribute('role') === 'heading')) {
            out.suspectEnglish.push(t.slice(0, 80));
          }
        }
      }
      out.rawKeys = [...new Set(out.rawKeys)].slice(0, 25);
      out.suspectEnglish = [...new Set(out.suspectEnglish)].slice(0, 25);
      return out;
    },
    { locale },
  );
}

// Detect presence of the 8 guidance-standard affordances.
async function scanGuidance(page) {
  return page.evaluate(() => {
    const q = (sel) => document.querySelectorAll(sel).length;
    const txt = (document.body.innerText || '').toLowerCase();
    return {
      heading: q('h1, h2, [role="heading"]') > 0,
      empty_state: /no .* yet|get started|nothing here|create your first|empty|add your first/i.test(document.body.innerText || ''),
      field_help: q('[data-help], [aria-describedby], [title]:not([title=""]), button[aria-label*="help" i], [data-tooltip]'),
      tooltips: q('[role="tooltip"], .tooltip, [data-radix-tooltip-content]'),
      first_run_tour: q('[data-tour], [data-tour-step], [data-product-tour], [aria-label*="tour" i]'),
      ai_confidence: /confidence|suggest|recommended/i.test(txt) ? q('[data-confidence], [class*="confidence" i]') : 0,
      presets: q('[data-preset], [data-template], select, [role="combobox"]'),
      progressive: q('[aria-expanded], details, [data-collapsible], [data-accordion]'),
    };
  });
}

async function safeShot(page, file) {
  try { await page.screenshot({ path: file, fullPage: false }); return true; }
  catch { return false; }
}

async function run() {
  const { keys, locales } = parseArgs();
  mkdirSync(OUTROOT, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 240)); });
  page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message.slice(0, 240)));

  await login(page);
  console.log('LOGGED IN at', page.url(), '\nmodules:', keys.join(','), '\nlocales:', locales.join(','));

  const report = { base: BASE, modules: {} };

  for (const key of keys) {
    const mod = MODULES[key];
    if (!mod) { console.log(`?? unknown module "${key}" - skipping`); continue; }
    const dir = join(OUTROOT, key);
    mkdirSync(dir, { recursive: true });
    const r = { label: mod.label, route: mod.route, passes: {} };
    const errStart = errors.length;

    // PASS 1 - SMOKE -------------------------------------------------------
    try {
      await page.goto(`${BASE}${mod.route}?lang=en`, { waitUntil: 'networkidle', timeout: 35000 });
    } catch (e) { r.passes.smoke_nav = 'nav-timeout: ' + e.message.slice(0, 120); }
    await page.waitForTimeout(2500);
    const url1 = page.url();
    const body1 = (await page.locator('body').innerText().catch(() => '')).trim();
    const crashed = /something went wrong|unexpected error|error boundary|cannot read|is not a function/i.test(body1.slice(0, 400));
    await safeShot(page, join(dir, 'pass1_smoke.png'));
    r.passes.smoke = {
      url: url1,
      redirected_to_login: /\/login/.test(url1),
      body_len: body1.length,
      looks_empty: body1.length < 40,
      crash_text: crashed,
      console_errors: errors.length - errStart,
    };

    // PASS 2 - INTERACT (real, non-destructive clicks) --------------------
    const interacted = [];
    const safeClickables = [
      'button[aria-label*="help" i]',
      'button[aria-label*="info" i]',
      '[data-help]',
      'button:has-text("What\'s this")',
      'button:has-text("Get started")',
      'button:has-text("Learn more")',
      'button:has-text("Add")',
      'button:has-text("New")',
      '[role="tab"]',
    ];
    let shot = 0;
    for (const sel of safeClickables) {
      try {
        const el = page.locator(sel).first();
        if (await el.isVisible({ timeout: 600 }).catch(() => false)) {
          await el.click({ timeout: 1500 }).catch(() => {});
          await page.waitForTimeout(700);
          shot++;
          await safeShot(page, join(dir, `pass2_interact_${shot}.png`));
          interacted.push(sel);
          // close any opened overlay before next click
          await page.keyboard.press('Escape').catch(() => {});
          await page.waitForTimeout(250);
        }
      } catch { /* selector not present - fine */ }
      if (shot >= 4) break;
    }
    r.passes.interact = { clicked: interacted, shots: shot, console_errors_after: errors.length - errStart };

    // PASS 3 - I18N (all-languages gate, representative set) ---------------
    const i18nByLocale = {};
    for (const loc of locales) {
      try {
        await page.goto(`${BASE}${mod.route}?lang=${loc}`, { waitUntil: 'networkidle', timeout: 35000 });
        await page.waitForTimeout(2200); // allow lazy locale chunk to hydrate
        const scan = await scanI18n(page, loc);
        await safeShot(page, join(dir, `pass3_i18n_${loc}.png`));
        i18nByLocale[loc] = scan;
      } catch (e) {
        i18nByLocale[loc] = { error: e.message.slice(0, 120) };
      }
    }
    r.passes.i18n = i18nByLocale;

    // PASS 4 - GUIDANCE presence -----------------------------------------
    try {
      await page.goto(`${BASE}${mod.route}?lang=en`, { waitUntil: 'networkidle', timeout: 35000 });
      await page.waitForTimeout(1800);
      r.passes.guidance = await scanGuidance(page);
      await safeShot(page, join(dir, 'pass4_guidance.png'));
    } catch (e) { r.passes.guidance = { error: e.message.slice(0, 120) }; }

    report.modules[key] = r;
    const s = r.passes.smoke;
    const leaks = Object.values(i18nByLocale).reduce((a, v) => a + ((v.rawKeys || []).length) + ((v.suspectEnglish || []).length), 0);
    console.log(`[${key}] smoke:${s.crash_text ? 'CRASH' : s.redirected_to_login ? 'LOGIN-REDIR' : s.looks_empty ? 'EMPTY' : 'ok'} bodyLen=${s.body_len} clicks=${shot} i18nLeaks=${leaks} errors=${s.console_errors}`);
  }

  writeFileSync(join(OUTROOT, 'report.json'), JSON.stringify(report, null, 2));
  console.log('\nTOTAL CONSOLE ERRORS:', errors.length);
  errors.slice(0, 25).forEach((e) => console.log('  ERR:', e));
  console.log('\nReport: qa-tests/ux-acceptance/report.json');
  console.log('Screenshots: qa-tests/ux-acceptance/<module>/passN*.png');
  await browser.close();
}

run().catch((e) => { console.error('FATAL', e); process.exit(1); });
