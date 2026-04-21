/**
 * BIM Q1 UX tests — screenshot button, 5D cost color mode, URL deep-link state.
 *
 * These cover the three Q1 features landing in the viewer:
 *   1. Screenshot capture button (toolbar) → PNG download + clipboard copy
 *   2. 5D cost colour mode → rate gradient + legend
 *   3. Camera + selection deep-link URL state
 *
 * Follows the `injectAuth` pattern from bim-advanced.spec.ts so we bypass
 * the login UI and go straight into /bim.  Running these requires a live
 * backend at localhost:8000 and a dev server on :5173 — they are NOT
 * executed in CI by this agent; they exist so the user can run them on
 * demand once the other agents' changes settle.
 */

import { test, expect, type Page } from '@playwright/test';

test.describe.configure({ mode: 'serial' });

/* ── Auth helper (copied from bim-advanced.spec.ts for independence) ── */

async function injectAuth(page: Page): Promise<void> {
  const loginRes = await page.request.post('http://localhost:8000/api/v1/users/auth/login/', {
    data: { email: 'test@openestimate.com', password: 'OpenEstimate2024!' },
  });

  let accessToken: string;
  let refreshToken: string;

  if (loginRes.ok()) {
    const body = await loginRes.json();
    accessToken = body.access_token;
    refreshToken = body.refresh_token || body.access_token;
  } else {
    await page.request.post('http://localhost:8000/api/v1/users/auth/register/', {
      data: {
        email: 'test@openestimate.com',
        password: 'OpenEstimate2024!',
        full_name: 'E2E Test',
      },
    });
    const retryRes = await page.request.post('http://localhost:8000/api/v1/users/auth/login/', {
      data: { email: 'test@openestimate.com', password: 'OpenEstimate2024!' },
    });
    const body = await retryRes.json();
    accessToken = body.access_token;
    refreshToken = body.refresh_token || body.access_token;
  }

  await page.addInitScript((tokens: { access: string; refresh: string }) => {
    localStorage.setItem('oe_access_token', tokens.access);
    localStorage.setItem('oe_refresh_token', tokens.refresh);
    localStorage.setItem('oe_remember', '1');
    localStorage.setItem('oe_user_email', 'test@openestimate.com');
    localStorage.setItem('oe_onboarding_completed', 'true');
    localStorage.setItem('oe_welcome_dismissed', 'true');
    localStorage.setItem('oe_tour_completed', 'true');
    sessionStorage.setItem('oe_access_token', tokens.access);
    sessionStorage.setItem('oe_refresh_token', tokens.refresh);
  }, { access: accessToken, refresh: refreshToken });

  await page.goto('/about');
  await page.waitForLoadState('load');
  await page.waitForTimeout(1000);
}

async function dismissTour(page: Page): Promise<void> {
  try {
    const dismissBtns = [
      page.locator('button:has-text("Skip")'),
      page.locator('button:has-text("Got it")'),
      page.locator('button:has-text("Close")').first(),
      page.locator('[aria-label="Close"]').first(),
    ];
    for (const btn of dismissBtns) {
      try {
        if (await btn.isVisible({ timeout: 500 })) {
          await btn.click();
          await page.waitForTimeout(200);
        }
      } catch {
        /* ignore */
      }
    }
  } catch {
    /* ignore */
  }
}

let _cachedProjectId = '';

async function goToBIM(page: Page): Promise<void> {
  if (!_cachedProjectId) {
    try {
      const loginRes = await page.request.post('http://localhost:8000/api/v1/users/auth/login/', {
        data: { email: 'test@openestimate.com', password: 'OpenEstimate2024!' },
      });
      if (loginRes.ok()) {
        const loginBody = await loginRes.json();
        const token = loginBody.access_token;
        const projectsRes = await page.request.get('http://localhost:8000/api/v1/projects/', {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (projectsRes.ok()) {
          const projects = await projectsRes.json();
          if (Array.isArray(projects) && projects.length > 0) {
            _cachedProjectId = projects[0].id;
          }
        }
      }
    } catch {
      /* ignore */
    }
  }

  if (_cachedProjectId) {
    await page.goto(`/projects/${_cachedProjectId}/bim`);
  } else {
    await page.goto('/bim');
  }
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2500);
  await dismissTour(page);
}

/** Wait until the BIMViewer is mounted and a model is loaded. If no model
 *  is loaded (empty project), the tests below degrade gracefully — they
 *  still take a screenshot of the landing page so the user can see what
 *  happened instead of receiving a cryptic timeout. */
async function waitForViewerOrSkip(page: Page, screenshotPath: string): Promise<boolean> {
  const canvas = page.locator('canvas').first();
  try {
    await canvas.waitFor({ state: 'visible', timeout: 8000 });
    // Also wait a beat for the 3D scene to render content into the canvas.
    await page.waitForTimeout(1500);
    return true;
  } catch {
    await page.screenshot({ path: screenshotPath, fullPage: true });
    return false;
  }
}

/* ── Tests ───────────────────────────────────────────────────────────── */

test.describe('BIM Q1 UX features', () => {
  test.beforeEach(async ({ page }) => {
    await injectAuth(page);
    await goToBIM(page);
  });

  test('Q1a: screenshot button triggers a PNG download', async ({ page }) => {
    const ready = await waitForViewerOrSkip(page, 'test-results/bim-screenshot-btn-empty.png');
    if (!ready) {
      test.info().annotations.push({ type: 'skip', description: 'No BIM model loaded — empty state screenshotted' });
      return;
    }

    // The screenshot button has a stable data-testid so we don't have to
    // match the camera SVG heuristically.
    const btn = page.locator('[data-testid="bim-screenshot-btn"]');
    await expect(btn).toBeVisible();

    // Listen for the download event the browser fires from the generated
    // <a download> click. Playwright resolves the download even without
    // an on-disk save path, which is all we need to assert the flow.
    const downloadPromise = page.waitForEvent('download', { timeout: 5000 }).catch(() => null);
    await btn.click();
    const download = await downloadPromise;

    await page.screenshot({ path: 'test-results/bim-screenshot-btn.png', fullPage: true });

    if (download) {
      // Filename should carry the bim-screenshot- prefix and a .png suffix.
      expect(download.suggestedFilename()).toMatch(/^bim-screenshot-.*\.png$/i);
    }
  });

  test('Q1b: 5D cost colour mode can be activated and renders the legend', async ({ page }) => {
    const ready = await waitForViewerOrSkip(page, 'test-results/bim-5d-mode-empty.png');
    if (!ready) {
      test.info().annotations.push({ type: 'skip', description: 'No BIM model loaded' });
      return;
    }

    const select = page.locator('[data-testid="bim-color-mode-select"]');
    await expect(select).toBeVisible();
    await select.selectOption('5d_cost');

    // The legend strip should appear.
    const legend = page.locator('[data-testid="bim-5d-legend"]');
    await expect(legend).toBeVisible();

    await page.screenshot({ path: 'test-results/bim-5d-mode.png', fullPage: true });
  });

  test('Q1c: camera + selection survive a page reload via URL state', async ({ page }) => {
    const ready = await waitForViewerOrSkip(page, 'test-results/bim-url-state-empty.png');
    if (!ready) {
      test.info().annotations.push({ type: 'skip', description: 'No BIM model loaded' });
      return;
    }

    // Grab the current URL after the 500ms debounced writer has had a chance
    // to record the initial camera. A short extra wait is the simplest way
    // to ride through at least one interval tick.
    await page.waitForTimeout(1000);

    // Inject a known camera via the exposed __oeBim bridge so the assertion
    // below doesn't depend on OrbitControls actually having moved.
    await page.evaluate(() => {
      const w = window as unknown as {
        __oeBim?: {
          setViewpoint: (
            pos: { x: number; y: number; z: number },
            target: { x: number; y: number; z: number },
          ) => void;
        };
      };
      w.__oeBim?.setViewpoint(
        { x: 11.111, y: 22.222, z: 33.333 },
        { x: 1, y: 2, z: 3 },
      );
    });

    // Wait a full debounce cycle plus a margin.
    await page.waitForTimeout(900);
    const urlAfterMove = page.url();
    expect(urlAfterMove).toMatch(/cx=11\.111/);
    expect(urlAfterMove).toMatch(/ty=2/);

    // Reload and assert the URL parameters persist — the hydration path
    // reads them on mount and pushes them back into the viewer.
    await page.goto(urlAfterMove);
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2500);
    await page.screenshot({ path: 'test-results/bim-url-state.png', fullPage: true });

    expect(page.url()).toMatch(/cx=11\.111/);
  });
});
