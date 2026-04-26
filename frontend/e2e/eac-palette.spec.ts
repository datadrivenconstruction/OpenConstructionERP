/**
 * E2E — EAC v2 block palette (RFC 35 §7, EAC-3.1).
 *
 * Verifies the palette renders, search filters items, and captures screenshots
 * of both states. The demo route `/eac/demo` is dev-only, behind RequireAuth,
 * so we hydrate auth tokens before navigating.
 *
 * Uses the v1.9 login helper which reads cached tokens from
 * `e2e/v1.9/.auth-token.txt` (written by global-setup) and injects them via
 * addInitScript — avoids rate limits on the /login form. Backend must be
 * running for the initial login to succeed; after that, the cached token is
 * reused across all parallel workers.
 */
import { expect, test } from '@playwright/test';

import { loginV19 } from './v1.9/helpers-v19';

test.describe('EAC block palette (EAC-3.1 scaffolding)', () => {
  test.beforeEach(async ({ page }) => {
    await loginV19(page);
  });

  test('renders palette in default state with categorized items', async ({ page }) => {
    // domcontentloaded — HMR websocket keeps networkidle from firing.
    await page.goto('/eac/demo', { waitUntil: 'domcontentloaded' });

    // Demo page loaded — lazy chunk first compile can take 30s+ on cold dev server.
    await expect(page.getByTestId('eac-demo-page')).toBeVisible({ timeout: 60_000 });

    // Palette visible, default expanded
    const palette = page.getByTestId('eac-block-palette');
    await expect(palette).toBeVisible();
    await expect(palette).toHaveAttribute('data-collapsed', 'false');

    // Category headers present
    await expect(page.getByTestId('eac-palette-category-selectors')).toBeVisible();
    await expect(page.getByTestId('eac-palette-category-logic')).toBeVisible();
    await expect(page.getByTestId('eac-palette-category-attributes')).toBeVisible();
    await expect(page.getByTestId('eac-palette-category-constraints')).toBeVisible();

    // Specific items present (proves the catalog rendered)
    await expect(page.getByTestId('eac-palette-item-selector.category')).toBeVisible();
    await expect(page.getByTestId('eac-palette-item-logic.and')).toBeVisible();

    await page.screenshot({
      path: 'test-results/eac-palette-default.png',
      fullPage: false,
    });
  });

  test('search filters palette items', async ({ page }) => {
    // domcontentloaded — HMR websocket keeps networkidle from firing.
    await page.goto('/eac/demo', { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('eac-demo-page')).toBeVisible({ timeout: 60_000 });

    const search = page.getByTestId('eac-palette-search');
    await search.fill('alias');

    // Alias attribute item still visible
    await expect(page.getByTestId('eac-palette-item-attr.alias')).toBeVisible();
    // Logic AND item now hidden because the label doesn't match "alias"
    await expect(page.getByTestId('eac-palette-item-logic.and')).toHaveCount(0);

    await page.screenshot({
      path: 'test-results/eac-palette-search.png',
      fullPage: false,
    });
  });

  test('triplet block is visible on the canvas placeholder', async ({ page }) => {
    // domcontentloaded — HMR websocket keeps networkidle from firing.
    await page.goto('/eac/demo', { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('eac-demo-page')).toBeVisible({ timeout: 60_000 });

    // The demo renders one TripletBlock with the alias→Thickness ≥ 240 mm pair
    await expect(page.getByTestId('eac-block-triplet').first()).toBeVisible();
  });
});
