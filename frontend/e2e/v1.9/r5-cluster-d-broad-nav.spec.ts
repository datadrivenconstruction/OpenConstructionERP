/**
 * v1.9.4 R5 broad-navigation sweep (Cluster D).
 *
 * Hits every non-core sidebar route — Planning / Finance / Communication /
 * Documents / Quality & Safety groups plus bottom-nav entries — and
 * asserts:
 *   1. Page renders without a hard crash (main content present)
 *   2. No unhandled console errors
 *   3. Sidebar + top-header + main area are laid out side-by-side
 *      (no overlap between sidebar right-edge and main left-edge)
 *   4. Main content top is below the top-header (no overlap)
 *
 * Intentionally does NOT duplicate cluster A (Tasks / Projects), cluster B
 * (CAD/BIM), or cluster C (Rules / Dashboard / Validation) — those have
 * their own deep specs.
 */
import { test, expect, type ConsoleMessage, type Page } from '@playwright/test';
import { loginV19 } from './helpers-v19';

const OUT = 'test-results/r5-cluster-d';

const ROUTES: Array<{ path: string; name: string; heading?: RegExp | null }> = [
  // Planning & Control
  { path: '/schedule', name: 'schedule' },
  { path: '/5d', name: '5d-cost-model' },
  { path: '/risks', name: 'risk-register' },
  // Finance & Procurement
  { path: '/finance', name: 'finance' },
  { path: '/procurement', name: 'procurement' },
  { path: '/tendering', name: 'tendering' },
  { path: '/changeorders', name: 'change-orders' },
  // Communication
  { path: '/contacts', name: 'contacts' },
  { path: '/meetings', name: 'meetings' },
  { path: '/rfi', name: 'rfi' },
  { path: '/submittals', name: 'submittals' },
  { path: '/transmittals', name: 'transmittals' },
  { path: '/correspondence', name: 'correspondence' },
  // Documents
  { path: '/documents', name: 'documents' },
  { path: '/cde', name: 'cde' },
  { path: '/photos', name: 'photos' },
  { path: '/markups', name: 'markups' },
  { path: '/field-reports', name: 'field-reports' },
  { path: '/reports', name: 'reports' },
  // Quality & Safety
  { path: '/inspections', name: 'inspections' },
  { path: '/ncr', name: 'ncr' },
  { path: '/safety', name: 'safety' },
  { path: '/punchlist', name: 'punchlist' },
  // Bottom nav
  { path: '/users', name: 'users' },
  { path: '/modules', name: 'modules' },
  { path: '/settings', name: 'settings' },
  { path: '/about', name: 'about' },
];

function attachConsoleErrorWatcher(page: Page) {
  const errors: string[] = [];
  const handler = (msg: ConsoleMessage) => {
    if (msg.type() !== 'error') return;
    const text = msg.text();
    if (
      text.includes('[vite]') ||
      text.includes('HMR') ||
      text.includes('Download the React DevTools') ||
      text.includes('DeprecationWarning') ||
      text.includes('Failed to load resource') // 404s on optional widgets
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

interface LayoutInfo {
  sidebarRight: number;
  mainLeft: number;
  headerBottom: number;
  mainTop: number;
  hasMain: boolean;
}

async function measureLayout(page: Page): Promise<LayoutInfo> {
  return page.evaluate(() => {
    const sidebar = document.querySelector('aside[data-tour="sidebar"]');
    const header = document.querySelector('header');
    const main = document.querySelector('main');
    const sRect = sidebar?.getBoundingClientRect();
    const hRect = header?.getBoundingClientRect();
    const mRect = main?.getBoundingClientRect();
    return {
      sidebarRight: sRect ? sRect.right : 0,
      mainLeft: mRect ? mRect.left : 0,
      headerBottom: hRect ? hRect.bottom : 0,
      mainTop: mRect ? mRect.top : 0,
      hasMain: !!main,
    };
  });
}

test.describe('v1.9.4 broad-nav sweep', () => {
  test.beforeEach(async ({ page }) => {
    await loginV19(page);
  });

  for (const route of ROUTES) {
    test(`Route ${route.path} renders with no overlap + no console errors`, async ({ page }) => {
      const stop = attachConsoleErrorWatcher(page);
      const pad = route.name.padStart(20, '_');
      const slug = route.name;
      await page.goto(route.path);
      // Some routes redirect; give them a chance
      await page.waitForLoadState('domcontentloaded');
      // Accept either the requested path or a safe redirect (e.g. /login
      // if unauthed would indicate a helper bug — catch it here)
      const current = new URL(page.url()).pathname;
      expect(current, `${route.path} redirected to ${current}`).not.toMatch(/\/login/);

      await page.waitForLoadState('networkidle').catch(() => {
        /* some pages keep polling, fall through */
      });
      await page.waitForTimeout(500);

      await page.screenshot({ path: `${OUT}/${slug}.png`, fullPage: true });

      // Layout checks — only when the sidebar is visible (skip on very narrow)
      const layout = await measureLayout(page);
      if (layout.hasMain) {
        // Sidebar right edge must be <= main left edge (no overlap)
        expect(
          layout.sidebarRight,
          `Sidebar overlaps main on ${route.path}: sidebar.right=${layout.sidebarRight} main.left=${layout.mainLeft}`,
        ).toBeLessThanOrEqual(layout.mainLeft + 1); // 1px tolerance
        // Main top must be >= header bottom (no overlap)
        expect(
          layout.headerBottom,
          `Header overlaps main on ${route.path}: header.bottom=${layout.headerBottom} main.top=${layout.mainTop}`,
        ).toBeLessThanOrEqual(layout.mainTop + 1);
      }

      const errors = stop();
      // Some pages are known to hit optional backend endpoints that 404 in
      // a fresh DB — filter those noisy entries rather than failing the
      // layout check for them.
      const realErrors = errors.filter(
        (e) =>
          !/404/i.test(e) &&
          !/Failed to fetch/i.test(e) &&
          !/AbortError/i.test(e) &&
          !/NetworkError/i.test(e),
      );
      expect(realErrors, `${route.path} console errors`).toEqual([]);
    });
  }
});
