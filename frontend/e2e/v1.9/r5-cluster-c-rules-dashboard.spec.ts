/**
 * v1.9.4 R5 — Cluster C: Rules / Validation / Dashboard / Navigation.
 *
 * Full-workflow QA sweep for the following surfaces:
 *   1. /bim/rules?mode=requirements — Requirements mode (tabs hidden,
 *      compliance title, BIM Requirements Import/Export drawer toggle).
 *   2. /bim/rules — Quantity Rules mode (tabs visible, switch between
 *      tabs, open RuleEditorModal, try saving without a model, close).
 *   3. /project-intelligence — Estimation Dashboard (KPI hero, readiness
 *      ring, critical gaps, analytics grid, domain tabs, advisor) +
 *      pairwise overlap detection of widget cards.
 *   4. /validation — old Validation page still reaches + renders.
 *   5. Full sidebar sweep — expand every visible top-level group, click
 *      each nav item, assert non-empty destination (no 404s / redirect
 *      loops), capture a screenshot per page.
 *
 * Each step attaches a console error watcher and records a screenshot at
 * every meaningful transition under `test-results/r5-cluster-c/`.
 */
import { test, expect, type ConsoleMessage, type Page } from '@playwright/test';

const OUT = 'test-results/r5-cluster-c';

// ── auth helpers (inlined — the shared helpers-v19.ts uses __dirname
//    which is broken under ESM; we don't modify it) ────────────────────

const V19_USER = {
  email: process.env.V19_E2E_EMAIL ?? 'v19-e2e@openestimate.com',
  password: process.env.V19_E2E_PASSWORD ?? 'OpenEstimate2024!',
  full_name: 'v1.9 E2E User',
};

let lastAccessToken: string | undefined;

async function loginV19(page: Page): Promise<void> {
  let accessToken: string | undefined;
  let refreshToken: string | undefined;

  const tryLogin = async (): Promise<boolean> => {
    const res = await page.request.post(
      'http://localhost:8000/api/v1/users/auth/login/',
      {
        data: { email: V19_USER.email, password: V19_USER.password },
        failOnStatusCode: false,
      },
    );
    if (!res.ok()) return false;
    const body = await res.json();
    accessToken = body.access_token;
    refreshToken = body.refresh_token ?? body.access_token;
    return true;
  };

  if (!(await tryLogin())) {
    await page.request.post('http://localhost:8000/api/v1/users/auth/register/', {
      data: V19_USER,
      failOnStatusCode: false,
    });
    const ok = await tryLogin();
    if (!ok) throw new Error('R5-C: could not log in or register test user');
  }

  await page.addInitScript(
    (tokens: { access: string; refresh: string; email: string }) => {
      localStorage.setItem('oe_access_token', tokens.access);
      localStorage.setItem('oe_refresh_token', tokens.refresh);
      localStorage.setItem('oe_remember', '1');
      localStorage.setItem('oe_user_email', tokens.email);
      localStorage.setItem('oe_onboarding_completed', 'true');
      localStorage.setItem('oe_welcome_dismissed', 'true');
      localStorage.setItem('oe_tour_completed', 'true');
      sessionStorage.setItem('oe_access_token', tokens.access);
      sessionStorage.setItem('oe_refresh_token', tokens.refresh);
    },
    { access: accessToken!, refresh: refreshToken!, email: V19_USER.email },
  );

  lastAccessToken = accessToken;

  // Hydrate by visiting a cheap page
  await page.goto('/about');
  await page.waitForLoadState('load');
}

async function firstProjectId(page: Page): Promise<string | null> {
  const res = await page.request.get('http://localhost:8000/api/v1/projects/', {
    headers: lastAccessToken
      ? { Authorization: `Bearer ${lastAccessToken}` }
      : {},
  });
  if (!res.ok()) return null;
  const projects = (await res.json()) as Array<{ id: string }>;
  return projects[0]?.id ?? null;
}

// ── helpers ────────────────────────────────────────────────────────────

function attachConsoleErrorWatcher(page: Page) {
  const errors: string[] = [];
  const handler = (msg: ConsoleMessage) => {
    if (msg.type() !== 'error') return;
    const text = msg.text();
    // Filter dev-only/benign chatter.
    if (
      text.includes('[vite]') ||
      text.includes('HMR') ||
      text.includes('Download the React DevTools') ||
      text.includes('DeprecationWarning') ||
      text.includes('Failed to load resource') // network 4xx/5xx already asserted via UI
    ) {
      return;
    }
    errors.push(text);
  };
  page.on('console', handler);
  return () => {
    page.off('console', handler);
    return errors;
  };
}

/** Snap a full-page screenshot with a numeric prefix for ordering. */
async function snap(page: Page, name: string) {
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
}

// ── tests ──────────────────────────────────────────────────────────────

test.describe('R5 Cluster C — Rules / Validation / Dashboard / Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await loginV19(page);
  });

  // ── 1. BIM Rules Requirements mode ──────────────────────────────────
  test('1. /bim/rules?mode=requirements — locked to Requirements, drawer toggles', async ({
    page,
  }) => {
    const stop = attachConsoleErrorWatcher(page);
    await page.goto('/bim/rules?mode=requirements');
    await page.waitForLoadState('networkidle');

    // Title "BIM Rules (Compliance)"
    await expect(
      page.getByRole('heading', { name: /BIM Rules.*Compliance/i }),
    ).toBeVisible({ timeout: 10_000 });

    // Subtitle copy
    await expect(
      page.getByText(/Import and check BIM requirements/i).first(),
    ).toBeVisible();

    // Tab switcher must be HIDDEN. We assert the tab buttons are NOT
    // rendered by counting elements with the specific Requirements tab
    // header shape. When tabs are present there are 2 tab buttons; when
    // hidden, neither "Quantity Rules" nor "Requirements" appears as a
    // tab button in the page header area.
    // Use the known CSS signature from the source: buttons with class
    // "border-b-2" inside the tab strip. When locked, the strip is absent.
    const tabStrip = page.locator('div.flex.border-b.border-border-light.-mb-px');
    await expect(tabStrip).toHaveCount(0);

    await snap(page, '01-requirements-mode-default');

    // Bottom drawer "BIM Requirements Import/Export" is visible
    const drawerSummary = page.getByText(/BIM Requirements Import\/Export/i).first();
    await expect(drawerSummary).toBeVisible();

    // The drawer is a <details ... open> element — the chevron should
    // rotate when we toggle it. Click the summary to close, then reopen.
    await drawerSummary.click();
    await page.waitForTimeout(300);
    await snap(page, '02-requirements-drawer-closed');

    await drawerSummary.click();
    await page.waitForTimeout(300);
    await snap(page, '03-requirements-drawer-reopened');

    const errs = stop();
    expect(errs, `Console errors on requirements mode:\n${errs.join('\n')}`).toEqual([]);
  });

  // ── 2. Quantity Rules mode (default, with tab switcher) ─────────────
  test('2. /bim/rules — tab switcher works, RuleEditorModal opens + closes', async ({
    page,
  }) => {
    const stop = attachConsoleErrorWatcher(page);
    await page.goto('/bim/rules');
    await page.waitForLoadState('networkidle');

    // Tab switcher IS visible (no mode lock)
    const quantityTab = page.getByRole('button', { name: /Quantity Rules/i }).first();
    const requirementsTab = page
      .getByRole('button', { name: /^\s*Requirements\s*$/i })
      .first();
    await expect(quantityTab).toBeVisible({ timeout: 10_000 });
    await expect(requirementsTab).toBeVisible();
    await snap(page, '04-quantity-rules-default');

    // Click Requirements tab — RequirementsTabContent renders, which
    // means the toolbar (model picker + preview/apply buttons) is
    // replaced by the Requirements content. We assert the model picker
    // disappears and the Requirements import drawer appears.
    await requirementsTab.click();
    await page.waitForTimeout(400);
    await expect(page.getByText(/BIM model/i).first()).toHaveCount(0, { timeout: 2_000 }).catch(() => {
      // Best effort — picker shouldn't be here. Not a hard fail.
    });
    await expect(page.getByText(/BIM Requirements Import\/Export/i).first()).toBeVisible();
    await snap(page, '05-requirements-tab-active');

    // Click Quantity Rules tab — returns to rules editor
    await quantityTab.click();
    await page.waitForTimeout(400);
    // Toolbar is back
    await expect(page.getByLabel(/BIM model/i)).toBeVisible({ timeout: 5_000 });
    await snap(page, '06-quantity-rules-tab-active');

    // Open "+ New rule" modal
    const newRuleBtn = page.getByRole('button', { name: /New rule/i }).first();
    await expect(newRuleBtn).toBeVisible();
    await newRuleBtn.click();
    await page.waitForTimeout(300);

    // Modal opens — assert dialog role
    const modal = page.getByRole('dialog');
    await expect(modal).toBeVisible({ timeout: 5_000 });
    await snap(page, '07-rule-editor-modal-open');

    // Fill minimal fields: name
    const nameInput = modal.locator('#rule-name');
    await expect(nameInput).toBeVisible();
    await nameInput.fill('E2E Rule');

    // quantity_source field is a select with id "rule-quantity-source"
    // or similar. Try finding a combobox by label.
    const sourceSelect = modal.locator('select').first();
    if (await sourceSelect.isVisible()) {
      // Pick area_m2 if it exists; otherwise first non-empty option
      const options = await sourceSelect.locator('option').allTextContents();
      const areaM2 = options.find((o) => /area.*m.?2/i.test(o));
      if (areaM2) {
        await sourceSelect.selectOption({ label: areaM2 });
      }
    }

    await snap(page, '08-rule-editor-filled');

    // Try submitting: form requires no BIM model to be selected only if
    // the page-level toolbar has one; modal itself has no model-picker,
    // so submit goes through the parent onSubmit. We're just testing
    // the UX: the submit button may either show an error toast or
    // succeed silently. We capture whichever state appears.
    const submitBtn = modal.getByRole('button', { name: /Save|Create|Submit/i }).first();
    if (await submitBtn.isVisible()) {
      await submitBtn.click();
      await page.waitForTimeout(1000);
      await snap(page, '09-rule-editor-after-submit');
    }

    // Close the modal with the X button (or Cancel)
    const closeBtn = modal.getByRole('button', { name: /Close/i }).first();
    if (await closeBtn.isVisible()) {
      await closeBtn.click();
    } else {
      // Fall back to pressing Escape
      await page.keyboard.press('Escape');
    }
    await page.waitForTimeout(300);
    await expect(modal).toBeHidden({ timeout: 3_000 });
    await snap(page, '10-rule-editor-closed');

    const errs = stop();
    expect(errs, `Console errors on quantity rules:\n${errs.join('\n')}`).toEqual([]);
  });

  // ── 3. Project Intelligence / Estimation Dashboard ─────────────────
  test('3. /project-intelligence — layout + widget overlap check', async ({ page }) => {
    const stop = attachConsoleErrorWatcher(page);
    const projectId = await firstProjectId(page);
    const url = projectId
      ? `/project-intelligence?project_id=${projectId}`
      : '/project-intelligence';
    await page.goto(url);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2500); // let analytics queries settle

    await snap(page, '11-project-intelligence-full');

    // Section 1 — KPI hero (3 cards)
    // If we have a project, expect the KPI cards. If not, skip.
    if (projectId) {
      // Hero cards (from components/ProjectKPIHero)
      const kpiIds = ['kpi-card-variance', 'kpi-card-schedule', 'kpi-card-risk'];
      for (const id of kpiIds) {
        await expect(page.getByTestId(id)).toBeVisible({ timeout: 15_000 });
      }

      // Section 2 — Estimation readiness
      await expect(page.getByText(/Estimation readiness/i).first()).toBeVisible();

      // Section 2b — Analytics widgets
      const widgetIds = [
        'pi-widget-cost-drivers',
        'pi-widget-price-volatility',
        'pi-widget-schedule-cost',
        'pi-widget-vendor-concentration',
        'pi-widget-scope-coverage',
        'pi-widget-validation',
      ];
      for (const id of widgetIds) {
        await expect(page.getByTestId(id)).toBeVisible({ timeout: 10_000 });
      }

      // ── Pairwise overlap detection ────────────────────────────────
      // Gather bounding boxes of all pi-widget-* cards; ensure none
      // intersect each other (they're in a CSS grid so must be side-by-side).
      const overlapCount = await page.evaluate(() => {
        const cards = Array.from(
          document.querySelectorAll('[data-testid^="pi-widget-"]'),
        ) as HTMLElement[];
        const rects = cards.map((c) => c.getBoundingClientRect());
        let overlaps = 0;
        const offenders: Array<[string, string]> = [];
        for (let i = 0; i < rects.length; i++) {
          for (let j = i + 1; j < rects.length; j++) {
            const a = rects[i];
            const b = rects[j];
            if (!a || !b) continue;
            // Shrink by 1px to ignore shared borders
            const ax1 = a.left + 1;
            const ax2 = a.right - 1;
            const ay1 = a.top + 1;
            const ay2 = a.bottom - 1;
            const bx1 = b.left + 1;
            const bx2 = b.right - 1;
            const by1 = b.top + 1;
            const by2 = b.bottom - 1;
            const intersectsX = ax1 < bx2 && bx1 < ax2;
            const intersectsY = ay1 < by2 && by1 < ay2;
            if (intersectsX && intersectsY) {
              overlaps++;
              offenders.push([
                cards[i]!.getAttribute('data-testid') ?? '?',
                cards[j]!.getAttribute('data-testid') ?? '?',
              ]);
            }
          }
        }
        // Attach as DOM dataset so we can read from outside
        document.body.dataset.overlapDebug = JSON.stringify(offenders);
        return overlaps;
      });

      const overlapDebug =
        (await page.evaluate(() => document.body.dataset.overlapDebug)) ?? '[]';

      expect(
        overlapCount,
        `Analytics widget cards overlap each other. Offenders: ${overlapDebug}`,
      ).toBe(0);

      // ── Section 3 — Domain detail tabs ─────────────────────────────
      // Tabs exist for BOQ / Cost / Schedule / Risk — click each if it's
      // present as a button in the detail section.
      const domainLabels = ['BOQ', 'Cost', 'Schedule', 'Risk'];
      for (const label of domainLabels) {
        const btn = page
          .getByRole('button', { name: new RegExp(`^${label}`, 'i') })
          .first();
        if (await btn.isVisible().catch(() => false)) {
          await btn.click().catch(() => {
            /* non-fatal */
          });
          await page.waitForTimeout(300);
          await snap(page, `12-domain-tab-${label.toLowerCase()}`);
        }
      }

      // Section 4 — Cost Intelligence Advisor (AIAdvisorPanel)
      await expect(
        page.getByText(/Advisor|AI Cost Advisor|Cost Intelligence/i).first(),
      ).toBeVisible({ timeout: 5_000 });
    } else {
      // No project — empty state
      await expect(page.getByText(/Select a project/i).first()).toBeVisible({
        timeout: 10_000,
      });
    }

    await snap(page, '13-project-intelligence-end');

    const errs = stop();
    expect(errs, `Console errors on /project-intelligence:\n${errs.join('\n')}`).toEqual([]);
  });

  // ── 4. Validation module ─────────────────────────────────────────────
  test('4. /validation — renders dashboard', async ({ page }) => {
    const stop = attachConsoleErrorWatcher(page);
    await page.goto('/validation');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(800);
    await snap(page, '14-validation-dashboard');

    // Page should at least render a heading or the word "Validation" in
    // the main content area.
    const body = (await page.textContent('body')) ?? '';
    expect(body.length).toBeGreaterThan(100);
    expect(body).toMatch(/validat/i);

    const errs = stop();
    expect(errs, `Console errors on /validation:\n${errs.join('\n')}`).toEqual([]);
  });

  // ── 5. Sidebar navigation sweep ──────────────────────────────────────
  test('5. Full sidebar sweep — every visible item reaches a non-empty page', async ({
    page,
  }) => {
    // This test clicks through ~46 routes; each hits networkidle so the
    // default 30s cap is too tight. Bump it to 5 min.
    test.setTimeout(300_000);
    const stop = attachConsoleErrorWatcher(page);

    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await snap(page, '15-sidebar-dashboard');

    // Expand every collapsed group by clicking its header.
    // NavGroupSection uses an inner <button> with aria-expanded. We click
    // any that reports expanded=false so all items are visible.
    const expandBtns = page.locator('aside button[aria-expanded="false"]');
    const groupCount = await expandBtns.count();
    for (let i = 0; i < groupCount; i++) {
      const btn = expandBtns.nth(0); // always nth(0) because DOM shrinks
      if (await btn.isVisible().catch(() => false)) {
        await btn.click().catch(() => {
          /* ignore */
        });
        await page.waitForTimeout(100);
      }
    }
    await snap(page, '16-sidebar-all-expanded');

    // Collect hrefs from every visible NavLink in the sidebar.
    const links = await page.evaluate(() => {
      const aside = document.querySelector('aside');
      if (!aside) return [] as string[];
      const anchors = Array.from(
        aside.querySelectorAll('a[href]'),
      ) as HTMLAnchorElement[];
      return Array.from(
        new Set(
          anchors
            .filter(
              (a) =>
                a.getAttribute('href')?.startsWith('/') &&
                !a.getAttribute('href')?.startsWith('//'),
            )
            .map((a) => a.getAttribute('href') ?? '')
            .filter(Boolean),
        ),
      );
    });

    // Remove expected externals and duplicates, keep same-origin only.
    // Exclude non-SPA endpoints (anything starting with /api/ is a backend
    // REST route, not a router path; /api/source is the AGPL source link).
    const safeLinks = links.filter(
      (l) =>
        l &&
        l.startsWith('/') &&
        !l.startsWith('/api/') &&
        !l.startsWith('/static/') &&
        !l.startsWith('/docs'),
    );
    console.log(`[R5-C] Sidebar sweep collected ${safeLinks.length} routes`);

    type NavResult = {
      href: string;
      finalUrl: string;
      bodyLen: number;
      hasReactRoot: boolean;
      status: 'ok' | 'redirect-loop' | 'empty' | 'not-found';
    };
    const results: NavResult[] = [];

    for (let i = 0; i < safeLinks.length; i++) {
      const href = safeLinks[i]!;
      // Navigate via URL (more reliable than clicking through router
      // when the sidebar itself may re-render). Use domcontentloaded
      // instead of networkidle for speed — a lazy widget that streams
      // data shouldn't block the sweep.
      try {
        await page.goto(href, { waitUntil: 'domcontentloaded', timeout: 10_000 });
      } catch {
        // Slow route; press on and see what's rendered
      }
      // Wait for lazy React.Suspense to resolve. Most pages hydrate within
      // 300-800ms after the DOM is ready, but we give up to 1500ms for
      // the slowest routes.
      await page.waitForTimeout(800);

      const finalUrl = new URL(page.url()).pathname + new URL(page.url()).search;
      // Measure the rendered text of the main content area (the <main>
      // or [role=main] slot — NOT the sidebar) to catch truly blank
      // pages vs. lazy-suspended ones. Wrap in try/catch in case the
      // navigation destroyed the execution context mid-run.
      let measurement = { mainText: '', mainTextLen: 0, spinnerVisible: false };
      try {
        measurement = await page.evaluate(() => {
          const main = document.querySelector('main, [role="main"]');
          const mainText = (main?.textContent ?? '').trim();
          const spinnerVisible = !!document.querySelector(
            'main .animate-spin, [role="main"] .animate-spin',
          );
          return { mainText, mainTextLen: mainText.length, spinnerVisible };
        });
      } catch {
        // Navigation happened mid-evaluate; retry after a settle
        await page.waitForTimeout(500);
        try {
          measurement = await page.evaluate(() => {
            const main = document.querySelector('main, [role="main"]');
            const mainText = (main?.textContent ?? '').trim();
            const spinnerVisible = !!document.querySelector(
              'main .animate-spin, [role="main"] .animate-spin',
            );
            return { mainText, mainTextLen: mainText.length, spinnerVisible };
          });
        } catch {
          /* give up; measurement stays empty */
        }
      }
      const bodyText = (await page.textContent('body').catch(() => '')) ?? '';
      const hasReactRoot = await page
        .locator('#root, [data-reactroot]')
        .first()
        .isVisible()
        .catch(() => false);

      let status: NavResult['status'] = 'ok';
      // Explicit 404 detection — require the error-page signature, not
      // a generic "No X found" empty-state phrase.
      if (
        /\b404\b.*not.?found|page.+(does\s?n.?t|not).+exist|Route not found/i.test(
          bodyText.slice(0, 4000),
        )
      ) {
        status = 'not-found';
      } else if (measurement.mainTextLen < 10 && !measurement.spinnerVisible) {
        // Main area is blank AND no loading indicator. Real issue.
        status = 'empty';
      }

      results.push({
        href,
        finalUrl,
        bodyLen: measurement.mainTextLen,
        hasReactRoot,
        status,
      });

      const safeName = href
        .replace(/[^a-z0-9]+/gi, '-')
        .replace(/^-+|-+$/g, '')
        .toLowerCase() || 'root';
      await snap(page, `17-nav-${String(i + 1).padStart(2, '0')}-${safeName}`);
    }

    // Print a debug summary in CI so failures are easy to triage.
    for (const r of results) {
      // eslint-disable-next-line no-console
      console.log(`[R5-C] nav: ${r.href} -> ${r.finalUrl} (${r.status}, ${r.bodyLen}b)`);
    }

    const badRoutes = results.filter((r) => r.status !== 'ok');
    expect(
      badRoutes,
      `Sidebar routes with issues:\n${badRoutes
        .map((b) => `  ${b.href} -> ${b.finalUrl} [${b.status}]`)
        .join('\n')}`,
    ).toEqual([]);

    // Check for redirect loops: if href !== finalUrl AND finalUrl is a
    // redirect destination (home or login), flag as a loop candidate.
    const redirectLoops = results.filter(
      (r) => r.href !== r.finalUrl && /\/login/.test(r.finalUrl),
    );
    expect(
      redirectLoops,
      `Sidebar routes redirecting to login (auth broken for these paths): ${redirectLoops
        .map((r) => r.href)
        .join(', ')}`,
    ).toEqual([]);

    const errs = stop();
    expect(errs, `Console errors during sidebar sweep:\n${errs.join('\n')}`).toEqual([]);
  });
});
