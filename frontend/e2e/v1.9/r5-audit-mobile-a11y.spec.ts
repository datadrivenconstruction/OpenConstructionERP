/**
 * v1.9 R5 audit — mobile responsive, tablet layout, keyboard navigation + focus
 * visibility. Three sub-audits, each grouped in its own describe block.
 *
 * Sub-audit 1: iPhone 13 (375x812) — full page screenshots + no horizontal
 * scroll + menu-button presence + best-effort text clipping detection.
 *
 * Sub-audit 2: iPad portrait (768x1024) — full page screenshots, informational.
 *
 * Sub-audit 3: Desktop (1280x720) — Tab 15 times per route, every focused
 * element is not <body> and has a visible focus style. Screenshots every 5 tabs.
 *
 * Source code is NOT modified — this is an observational audit. Failures in
 * assertions report issues to the parent triage flow.
 */
import { test, expect, type ConsoleMessage, type Page } from '@playwright/test';
import { loginV19 } from './helpers-v19';

const MOBILE_OUT = 'test-results/r5-audit-mobile';
const TABLET_OUT = 'test-results/r5-audit-tablet';
const KEYBOARD_OUT = 'test-results/r5-audit-keyboard';

/** Same filter list as r5-verification.spec.ts — 403/404 from optional endpoints are expected. */
function attachConsoleErrorWatcher(page: Page) {
  const errors: string[] = [];
  const handler = (msg: ConsoleMessage) => {
    if (msg.type() === 'error') {
      const text = msg.text();
      if (
        text.includes('[vite]') ||
        text.includes('HMR') ||
        text.includes('Download the React DevTools') ||
        text.includes('DeprecationWarning') ||
        /Failed to load resource.*\(403\)/i.test(text) ||
        /Failed to load resource.*status of 403/i.test(text) ||
        /Failed to load resource.*\(404\)/i.test(text) ||
        /Failed to load resource.*status of 404/i.test(text)
      ) {
        return;
      }
      errors.push(text);
    }
  };
  page.on('console', handler);
  return () => {
    page.off('console', handler);
    return errors;
  };
}

/** Routes covered by the mobile + tablet sub-audits. Index determines screenshot prefix. */
const ROUTES: Array<{ path: string; slug: string }> = [
  { path: '/', slug: 'dashboard' },
  { path: '/projects', slug: 'projects' },
  { path: '/boq', slug: 'boq' },
  { path: '/tasks', slug: 'tasks' },
  { path: '/takeoff?tab=measurements', slug: 'takeoff-measurements' },
  { path: '/dwg-takeoff', slug: 'dwg-takeoff' },
  { path: '/data-explorer', slug: 'data-explorer' },
  { path: '/bim', slug: 'bim' },
  { path: '/bim/rules?mode=requirements', slug: 'bim-rules-requirements' },
  { path: '/project-intelligence', slug: 'project-intelligence' },
  { path: '/about', slug: 'about' },
];

/** Routes for the keyboard sub-audit. */
const KEYBOARD_ROUTES: Array<{ path: string; slug: string }> = [
  { path: '/', slug: 'dashboard' },
  { path: '/projects', slug: 'projects' },
  { path: '/tasks', slug: 'tasks' },
  { path: '/bim/rules?mode=requirements', slug: 'bim-rules-requirements' },
  { path: '/project-intelligence', slug: 'project-intelligence' },
];

/**
 * Evaluate the page and return `true` if *any* element on the page:
 *   - has computed `overflow-x: hidden` or `overflow: hidden`
 *   - AND its content (scrollWidth) exceeds its box (clientWidth) by more than 5px
 *   - AND it contains text that is visibly clipped (scrollWidth > clientWidth + 5)
 *
 * Returns array of short diagnostic strings for the first 5 offenders.
 */
async function findClippedText(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = [];
    const MAX = 5;
    const all = Array.from(document.querySelectorAll<HTMLElement>('body *'));
    for (const el of all) {
      if (out.length >= MAX) break;
      const style = getComputedStyle(el);
      const ox = style.overflowX;
      const ov = style.overflow;
      const clipping = ox === 'hidden' || ov === 'hidden';
      if (!clipping) continue;
      // Must actually contain direct text, not just whitespace
      const textLen = (el.innerText ?? '').trim().length;
      if (textLen < 4) continue;
      if (el.scrollWidth > el.clientWidth + 5) {
        const tag = el.tagName.toLowerCase();
        const cls = (el.className || '').toString().slice(0, 40);
        const sample = (el.innerText ?? '').trim().slice(0, 40);
        out.push(`${tag}.${cls} scroll=${el.scrollWidth} client=${el.clientWidth} "${sample}"`);
      }
    }
    return out;
  });
}

async function measureHorizontalScroll(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth);
}

/**
 * Best-effort menu-button detection for mobile. Passes if any element matching
 * the common menu-button patterns exists in the header (aria-label Menu, a
 * hamburger-style button, or a sidebar toggle button).
 */
async function hasMobileMenuButton(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    // Match common patterns: aria-label includes menu/navigation/toggle,
    // button containing an SVG with 3 horizontal lines, or data-mobile-menu
    const candidates = Array.from(
      document.querySelectorAll<HTMLElement>(
        'button[aria-label], [role="button"][aria-label], [data-mobile-menu], button[data-sidebar-toggle]',
      ),
    );
    for (const el of candidates) {
      const lbl = (el.getAttribute('aria-label') ?? '').toLowerCase();
      if (/menu|navigation|sidebar|toggle|open nav/.test(lbl)) {
        const style = getComputedStyle(el);
        if (style.display !== 'none' && style.visibility !== 'hidden') return true;
      }
    }
    // Fallback: any visible button with Lucide/Heroicons-style 3-line SVG in the top 80px
    const btns = Array.from(document.querySelectorAll<HTMLButtonElement>('header button, nav button, [class*="header"] button'));
    for (const b of btns) {
      const rect = b.getBoundingClientRect();
      if (rect.top > 100) continue;
      const svg = b.querySelector('svg');
      if (!svg) continue;
      // Heuristic: SVG with multiple line/path elements often indicates hamburger
      const lines = svg.querySelectorAll('line, path');
      if (lines.length >= 2) return true;
    }
    return false;
  });
}

/** Read info about the currently focused element. */
async function getFocusInfo(page: Page): Promise<{
  tagName: string;
  role: string | null;
  text: string;
  outline: string;
  boxShadow: string;
  hasRing: boolean;
  isBody: boolean;
}> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el) {
      return {
        tagName: 'NULL',
        role: null,
        text: '',
        outline: 'none',
        boxShadow: 'none',
        hasRing: false,
        isBody: true,
      };
    }
    const style = getComputedStyle(el);
    const text = ((el.textContent ?? '') + ' ' + (el.getAttribute('aria-label') ?? ''))
      .trim()
      .slice(0, 40);
    const hasRing = /ring|focus/.test((el.className ?? '').toString());
    return {
      tagName: el.tagName,
      role: el.getAttribute('role'),
      text,
      outline: style.outline || 'none',
      boxShadow: style.boxShadow || 'none',
      hasRing,
      isBody: el.tagName === 'BODY' || el === document.body,
    };
  });
}

function hasVisibleFocusStyle(info: {
  outline: string;
  boxShadow: string;
  hasRing: boolean;
}): boolean {
  const outlineOk = info.outline && info.outline !== 'none' && !/0px/.test(info.outline);
  const shadowOk = info.boxShadow && info.boxShadow !== 'none' && /rgb/i.test(info.boxShadow);
  return outlineOk || shadowOk || info.hasRing;
}

// --------------------------------------------------------------------------
// Sub-audit 1: Mobile responsive (iPhone 13, 375x812)
// --------------------------------------------------------------------------

test.describe('R5 audit — Mobile responsive (iPhone 13)', () => {
  test.beforeEach(async ({ page }) => {
    await loginV19(page);
    await page.setViewportSize({ width: 375, height: 812 });
  });

  for (let i = 0; i < ROUTES.length; i++) {
    const route = ROUTES[i];
    const idx = String(i + 1).padStart(2, '0');
    test(`mobile ${route.path}`, async ({ page }) => {
      test.setTimeout(60_000);
      const stop = attachConsoleErrorWatcher(page);

      await page.goto(route.path);
      await page
        .waitForLoadState('networkidle', { timeout: 15_000 })
        .catch(() => {
          /* some pages keep opening websockets — don't fail the audit for that */
        });
      await page.waitForTimeout(800);

      await page.screenshot({
        path: `${MOBILE_OUT}/${idx}-${route.slug}.png`,
        fullPage: true,
      });

      const scrollWidth = await measureHorizontalScroll(page);
      const clipping = await findClippedText(page);
      const menuBtn = await hasMobileMenuButton(page);

      // Report findings via soft expect — we want to see ALL failures, not
      // just the first per test, and the screenshot is already captured.
      expect
        .soft(scrollWidth, `horizontal overflow on ${route.path}`)
        .toBeLessThanOrEqual(380);
      expect
        .soft(menuBtn, `no mobile menu button on ${route.path}`)
        .toBe(true);
      expect
        .soft(clipping, `clipped text on ${route.path}: ${clipping.join(' | ')}`)
        .toEqual([]);

      const errors = stop();
      expect.soft(errors, `console errors on ${route.path}`).toEqual([]);
    });
  }
});

// --------------------------------------------------------------------------
// Sub-audit 2: Tablet (iPad portrait, 768x1024)
// --------------------------------------------------------------------------

test.describe('R5 audit — Tablet (iPad portrait)', () => {
  test.beforeEach(async ({ page }) => {
    await loginV19(page);
    await page.setViewportSize({ width: 768, height: 1024 });
  });

  for (let i = 0; i < ROUTES.length; i++) {
    const route = ROUTES[i];
    const idx = String(i + 1).padStart(2, '0');
    test(`tablet ${route.path}`, async ({ page }) => {
      test.setTimeout(60_000);
      const stop = attachConsoleErrorWatcher(page);

      await page.goto(route.path);
      await page
        .waitForLoadState('networkidle', { timeout: 15_000 })
        .catch(() => {
          /* ignore persistent ws */
        });
      await page.waitForTimeout(800);

      await page.screenshot({
        path: `${TABLET_OUT}/${idx}-${route.slug}.png`,
        fullPage: true,
      });

      const scrollWidth = await measureHorizontalScroll(page);
      const clipping = await findClippedText(page);

      // Tablet is more forgiving — only flag clear horizontal overflow + clips.
      expect
        .soft(scrollWidth, `tablet horizontal overflow on ${route.path}`)
        .toBeLessThanOrEqual(775);
      expect
        .soft(clipping, `tablet clipped text on ${route.path}: ${clipping.join(' | ')}`)
        .toEqual([]);

      const errors = stop();
      expect.soft(errors, `tablet console errors on ${route.path}`).toEqual([]);
    });
  }
});

// --------------------------------------------------------------------------
// Sub-audit 3: Keyboard navigation + focus visibility (desktop 1280x720)
// --------------------------------------------------------------------------

test.describe('R5 audit — Keyboard + focus visibility (desktop)', () => {
  test.beforeEach(async ({ page }) => {
    await loginV19(page);
    await page.setViewportSize({ width: 1280, height: 720 });
  });

  for (let i = 0; i < KEYBOARD_ROUTES.length; i++) {
    const route = KEYBOARD_ROUTES[i];
    const idx = String(i + 1).padStart(2, '0');
    test(`keyboard ${route.path}`, async ({ page }) => {
      test.setTimeout(60_000);
      const stop = attachConsoleErrorWatcher(page);

      await page.goto(route.path);
      await page
        .waitForLoadState('networkidle', { timeout: 15_000 })
        .catch(() => {
          /* ignore */
        });
      await page.waitForTimeout(800);

      // Focus <body> as baseline so Tab starts from the document start
      await page.evaluate(() => {
        (document.activeElement as HTMLElement | null)?.blur?.();
        document.body.focus();
      });

      const findings: string[] = [];

      for (let step = 1; step <= 15; step++) {
        await page.keyboard.press('Tab');
        // Tiny wait so focus handlers can run
        await page.waitForTimeout(80);
        const info = await getFocusInfo(page);

        if (info.isBody) {
          findings.push(
            `tab ${step}: focus fell off (activeElement=<body>)`,
          );
        } else if (!hasVisibleFocusStyle(info)) {
          findings.push(
            `tab ${step}: no visible focus on <${info.tagName.toLowerCase()}>` +
              ` "${info.text}" (outline=${info.outline}, shadow=${info.boxShadow.slice(0, 40)})`,
          );
        }

        if (step % 5 === 0) {
          await page.screenshot({
            path: `${KEYBOARD_OUT}/${idx}-${route.slug}-tab-${step}.png`,
            fullPage: false,
          });
        }
      }

      expect
        .soft(findings, `keyboard issues on ${route.path}`)
        .toEqual([]);

      const errors = stop();
      expect.soft(errors, `keyboard console errors on ${route.path}`).toEqual([]);
    });
  }
});
