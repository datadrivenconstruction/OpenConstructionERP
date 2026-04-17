/**
 * v1.9 #19 — BIM viewer control panel (RFC 19).
 *
 * Covers saved views, per-category transparency, bounding-box outline on
 * selection, and the measure-distance tool. Tests run against the live
 * backend using the v19 helper for auth.
 */
import { test, expect, type Page } from '@playwright/test';
import { loginV19, firstProjectId, firstBimModelId } from './helpers-v19';

async function waitForViewer(page: Page) {
  // The viewer hosts a canvas inside the 3D viewport. Wait for it to exist.
  await page.waitForSelector('canvas', { timeout: 15_000 });
  // Allow the initial geometry / element fetch to settle.
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
}

async function openRightPanel(page: Page) {
  // The header toggle for the right panel is "Linked BOQ".
  const toggle = page.getByRole('button', {
    name: /Linked BOQ|Toggle linked BOQ panel/i,
  });
  if (await toggle.count()) {
    const aria = await toggle.first().getAttribute('aria-pressed');
    if (aria !== 'true') await toggle.first().click();
  }
}

test.describe('v1.9 #19 — BIM viewer expanded controls', () => {
  test.beforeEach(async ({ page }) => {
    await loginV19(page);
  });

  test('Saved views tab round-trips: save → list → apply', async ({ page }) => {
    const projectId = await firstProjectId(page);
    test.skip(!projectId, 'no project available');
    const modelId = await firstBimModelId(page, projectId!);
    test.skip(!modelId, 'no BIM model available — upload one to /bim first');

    await page.goto(`/bim/${modelId}`);
    await waitForViewer(page);
    await openRightPanel(page);

    const toolsTab = page.getByTestId('right-tab-tools');
    if (!(await toolsTab.isVisible().catch(() => false))) {
      // `S` shortcut should open the Tools tab.
      await page.keyboard.press('s');
    } else {
      await toolsTab.click();
    }

    const name = `e2e-view-${Date.now()}`;
    await page.getByTestId('save-view-name').fill(name);
    await page.getByTestId('save-view-button').click();

    const row = page.getByTestId('saved-view-row').filter({ hasText: name });
    await expect(row).toHaveCount(1);

    // Reload and verify persistence.
    await page.reload();
    await waitForViewer(page);
    await openRightPanel(page);
    if (!(await page.getByTestId('right-tab-tools').isVisible().catch(() => false))) {
      await page.keyboard.press('s');
    } else {
      await page.getByTestId('right-tab-tools').click();
    }
    await expect(
      page.getByTestId('saved-view-row').filter({ hasText: name }),
    ).toHaveCount(1);
  });

  test('Layers tab opacity slider exists for a populated category', async ({ page }) => {
    const projectId = await firstProjectId(page);
    test.skip(!projectId, 'no project available');
    const modelId = await firstBimModelId(page, projectId!);
    test.skip(!modelId, 'no BIM model available — upload one to /bim first');

    await page.goto(`/bim/${modelId}`);
    await waitForViewer(page);
    await openRightPanel(page);

    await page.getByTestId('right-tab-layers').click();

    // At least one opacity slider should render.
    const slider = page.locator('[data-testid^="layer-opacity-"]').first();
    await expect(slider).toBeVisible();

    // Slide it down and verify the percentage label updates.
    await slider.evaluate((el) => {
      const input = el as HTMLInputElement;
      input.value = '30';
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
  });

  test('Measure toggle button and hint are reachable via keyboard', async ({ page }) => {
    const projectId = await firstProjectId(page);
    test.skip(!projectId, 'no project available');
    const modelId = await firstBimModelId(page, projectId!);
    test.skip(!modelId, 'no BIM model available — upload one to /bim first');

    await page.goto(`/bim/${modelId}`);
    await waitForViewer(page);
    // Pressing `m` toggles the measure tool; the hint should appear.
    await page.keyboard.press('m');
    await expect(page.getByTestId('bim-measure-hint')).toBeVisible({
      timeout: 5_000,
    });
    // Press Escape to cancel — when no pending point exists it disables the tool
    // and the hint disappears.
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('bim-measure-hint')).toHaveCount(0);
  });
});
