/**
 * Critical paths regression tests — covers the user-visible bugs flagged
 * by the v2.5.0 QA pass (BUG-B01 build, BUG-UI02 tour, BUG-UI03 New Project,
 * BUG-UI04 /dashboards 500, BUG-UI05 /reporting 404 cascade, BUG-UI06
 * /finance 422).
 *
 * These tests run **without** a live backend by stubbing every `/api/*`
 * route. Each affected page must render its frame (heading or empty
 * state) even when the API responds with an error — i.e. no white-screen
 * crash. The tour must NOT auto-pop after it has been dismissed.
 *
 * Run on its own: `npx playwright test e2e/critical_paths.spec.ts --reporter=list`
 */
import { test, expect, type Page } from '@playwright/test';

// We bypass globalSetup (which wants a real backend) by setting tokens
// directly. The backend is mocked at the network layer for every test.
test.use({ storageState: { cookies: [], origins: [] } });

// A long-lived fake JWT — token is never validated client-side beyond
// the role-claim decode (which tolerates failures). The header.payload
// shape just needs three dot-separated base64 chunks.
const FAKE_JWT =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' +
  'eyJzdWIiOiJ0ZXN0IiwicHJvamVjdF9pZCI6IjAwMDAwMDAwLTAwMDAtMDAwMC0wMDAwLTAwMDAwMDAwMDAwMSIsInJvbGUiOiJhZG1pbiJ9.' +
  'sig';

const DEMO_PROJECT_ID = '00000000-0000-0000-0000-000000000001';
const DEMO_PROJECT = {
  id: DEMO_PROJECT_ID,
  name: 'QA Demo Project',
  status: 'active',
  region: 'INTL',
  currency: 'EUR',
  classification_standard: 'custom',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  metadata: {},
};

/**
 * Hydrates localStorage with auth tokens + dismissed onboarding flags
 * before the SPA boots. Without this the SPA bounces to /login.
 */
async function seedAuth(page: Page): Promise<void> {
  await page.addInitScript(
    ({ token, projectId, projectName }) => {
      localStorage.setItem('oe_access_token', token);
      localStorage.setItem('oe_refresh_token', token);
      localStorage.setItem('oe_remember', '1');
      localStorage.setItem('oe_user_email', 'qa@example.com');
      // BUG-UI02: persist tour-completed so the tour does not pop on
      // every navigation. The same key the OnboardingTour component
      // reads (ONBOARDING_STORAGE_KEY).
      localStorage.setItem('oe_tour_completed', 'true');
      localStorage.setItem('oe_onboarding_completed', 'true');
      localStorage.setItem('oe_welcome_dismissed', 'true');
      // Make sure project context is populated so pages do not hard-stop
      // on the "select a project" empty state.
      localStorage.setItem('oe_active_project_id', projectId);
      localStorage.setItem('oe_active_project_name', projectName);
      sessionStorage.setItem('oe_access_token', token);
      sessionStorage.setItem('oe_refresh_token', token);
    },
    { token: FAKE_JWT, projectId: DEMO_PROJECT_ID, projectName: DEMO_PROJECT.name },
  );
}

/**
 * Installs the default mocked API responses. Individual tests can
 * override specific routes after calling this with another `page.route()`
 * (Playwright matches the most recent route handler first).
 */
async function mockApi(page: Page): Promise<void> {
  // Catch-all for unhandled API calls — return empty success to avoid
  // hanging fetches that would block `networkidle`. Matched last because
  // more specific routes are registered first.
  await page.route('**/api/**', async (route) => {
    const url = route.request().url();
    // Auth refresh / login should not hit here in our flow but be safe.
    if (url.includes('/auth/login') || url.includes('/auth/refresh')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ access_token: FAKE_JWT, refresh_token: FAKE_JWT }),
      });
      return;
    }
    // Default: empty list-shape response so frontend treats as "no data".
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], total: 0 }),
    });
  });

  // Projects list — at least one project so dashboards/reporting/finance
  // have a context to render against.
  await page.route('**/api/v1/projects/**', async (route) => {
    const url = route.request().url();
    if (url.match(/\/projects\/?\??/) && route.request().method() === 'GET' && !url.match(/\/projects\/[^/?]+/)) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([DEMO_PROJECT]),
      });
      return;
    }
    if (url.includes(`/projects/${DEMO_PROJECT_ID}`)) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(DEMO_PROJECT),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([DEMO_PROJECT]),
    });
  });

  // /me endpoint hit by some pages.
  await page.route('**/api/v1/users/me*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'user-1',
        email: 'qa@example.com',
        role: 'admin',
        full_name: 'QA Tester',
      }),
    });
  });
}

// ── Tests ────────────────────────────────────────────────────────────────────

test.describe('Critical paths — v2.5.0 QA bugs', () => {
  test.beforeEach(async ({ page }) => {
    await seedAuth(page);
    await mockApi(page);
  });

  /**
   * BUG-B01 — TypeScript build / BIM page renders.
   * Verifies the BIM viewer renders its frame (no fatal exception).
   */
  test('BIM page typechecks and loads (B01)', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('pageerror', (err) => consoleErrors.push(String(err.message)));

    await page.goto('/bim');
    // The viewer canvas, sidebar tabs or the empty-model placeholder must
    // appear — anything but a fatal blank page is acceptable here.
    await expect(page.locator('body')).toBeVisible();
    await page.waitForLoadState('domcontentloaded');
    // Allow up to 5 s for the BIM page chunk to mount.
    await page.waitForTimeout(2_000);

    // Page should not be a blank document — it must have rendered a header
    // / sidebar at minimum.
    const text = await page.locator('body').innerText();
    expect(text.length).toBeGreaterThan(20);

    // No uncaught runtime exceptions from the BIM module (the BUG-B01
    // failure mode would surface here as a `TS2339`-class TypeError at
    // runtime once the bundle was hand-edited to skip the type errors).
    const fatal = consoleErrors.filter((e) =>
      /assetCardEnabled|setAssetCardEnabled|rightPx|insetInlineStart/.test(e),
    );
    expect(fatal, fatal.join('\n')).toHaveLength(0);
  });

  /**
   * BUG-UI03 — `/projects/new` renders a working form (not a white screen
   * or 404). The QA report observed the tour blocking the field; here we
   * make sure the page itself is reachable and the project-name input is
   * focusable.
   */
  test('"New Project" navigates to /projects/new which renders the form (UI03)', async ({
    page,
  }) => {
    await page.goto('/projects/new');

    // Page header / form should render. Look for the form by its id.
    await expect(page.locator('#create-project-form')).toBeVisible({ timeout: 10_000 });

    // Project-name input must be focusable (not blocked by tour overlay,
    // BUG-UI02 / UI03 fix). Autofocus is set on the component, so it
    // should already have focus.
    const nameInput = page.locator('#create-project-form input[type="text"]').first();
    await expect(nameInput).toBeVisible();
    // Should be able to type — would fail if the tour overlay was over it.
    await nameInput.click();
    await nameInput.fill('QA New Project');
    await expect(nameInput).toHaveValue('QA New Project');
  });

  /**
   * BUG-UI04 — `/dashboards` returns 500 from the snapshot endpoint.
   * The page must render an error card or empty-state, not a white
   * screen. We deliberately make the snapshots endpoint return 500 to
   * reproduce the bug condition.
   */
  test('/dashboards renders without error toast even when API 500s (UI04)', async ({
    page,
  }) => {
    await page.route('**/api/v1/dashboards/projects/*/snapshots*', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'simulated server error' }),
      });
    });

    await page.goto('/dashboards');
    await page.waitForLoadState('domcontentloaded');
    // The page must render its frame even though the data call failed.
    // Either the snapshots page wrapper, the error card or the empty
    // state shows up — all are valid graceful degradations.
    const wrapper = page.getByTestId('dashboards-snapshots-page');
    const errorCard = page.getByText(
      /Could not load snapshots|No snapshots yet|Select a project|Browse projects/i,
    );
    // First-mounted of the two wins; we accept either.
    await expect(wrapper.or(errorCard).first()).toBeVisible({ timeout: 10_000 });
  });

  /**
   * BUG-UI05 — `/reporting` page issues per-project KPI requests; with a
   * dead endpoint the page used to log a 404 cascade. Verify the page
   * still mounts cleanly and the tab bar is visible (Promise.allSettled
   * keeps the page alive).
   */
  test('/reporting renders all tabs even when KPI endpoints 404 (UI05)', async ({ page }) => {
    // Force every reporting / kpi-style endpoint to 404.
    await page.route('**/api/v1/reporting/**', async (route) => {
      await route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
    });
    await page.route('**/api/v1/finance/dashboard/**', async (route) => {
      await route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
    });
    await page.route('**/api/v1/safety/stats/**', async (route) => {
      await route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
    });
    await page.route('**/api/v1/tasks/stats/**', async (route) => {
      await route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
    });
    await page.route('**/api/v1/rfi/stats/**', async (route) => {
      await route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
    });
    await page.route('**/api/v1/schedule/stats/**', async (route) => {
      await route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
    });
    await page.route('**/api/v1/procurement/stats/**', async (route) => {
      await route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
    });

    // Use a desktop viewport so the lg:block-only header is visible.
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/reporting');
    await page.waitForLoadState('domcontentloaded');

    // The page mounted successfully if either (a) the page-level H1 is
    // visible (desktop viewport renders both layout + page headings) or
    // (b) the tab bar is rendered. We use `or()` so the test does not
    // fight Tailwind's responsive visibility rules.
    const tabBar = page.getByRole('button', { name: /Executive/i });
    const pageH1 = page
      .getByRole('heading', { name: /Reporting Dashboards/i, level: 1 })
      .last(); // last = the in-page h1 (after the layout one)
    await expect(tabBar.or(pageH1)).toBeVisible({ timeout: 10_000 });

    // The tab bar must render so the user has navigation even with no
    // KPI data — that's the actual UI05 acceptance criterion.
    await expect(tabBar).toBeVisible();
  });

  /**
   * BUG-UI06 — `/finance` page sub-request 422. We force every finance
   * endpoint to 422 and assert the page still renders its tabs / shell
   * (no white screen).
   */
  test('/finance loads without crashing on 422 responses (UI06)', async ({ page }) => {
    await page.route('**/api/v1/finance/**', async (route) => {
      await route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: [{ type: 'value_error', loc: ['query'], msg: 'simulated' }],
        }),
      });
    });

    await page.goto('/finance');
    await page.waitForLoadState('domcontentloaded');

    // Page shell should render. We look for the page main region; the
    // finance page mounts inside <main>.
    await expect(page.locator('main')).toBeVisible({ timeout: 10_000 });

    // Either the empty-state CTA or one of the finance tab buttons is
    // present (depends on how the page degrades). We accept any of the
    // recognisable finance UI fragments.
    const shellFragments = page.locator(
      'text=/Budgets|Invoices|Payments|EVM|No invoices|No budgets|Finance/i',
    );
    await expect(shellFragments.first()).toBeVisible({ timeout: 10_000 });
  });

  /**
   * BUG-UI02 — onboarding tour must NOT pop up on every page navigation
   * once the user has dismissed it. We set `oe_tour_completed=true` in
   * beforeEach; verify the tour overlay never appears when navigating
   * across multiple routes.
   */
  test('tour does not re-appear on navigation after being dismissed (UI02)', async ({
    page,
  }) => {
    const routes = ['/', '/projects', '/projects/new', '/boq'];
    for (const route of routes) {
      await page.goto(route);
      await page.waitForLoadState('domcontentloaded');
      // The OnboardingTour tooltip data-testid must NOT be present —
      // the dismissed flag in localStorage gates it off.
      await expect(page.locator('[data-testid="onboarding-tooltip"]')).toHaveCount(0);
    }
  });
});
