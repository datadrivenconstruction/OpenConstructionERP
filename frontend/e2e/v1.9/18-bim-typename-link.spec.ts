/**
 * v1.9 #18 — BIM Type Name grouping: Link-to-BOQ and Save-as-group buttons
 * must remain visible when the user picks a grouping mode (Type Name,
 * Category, etc.) without narrowing the visible-element subset via an
 * explicit filter.
 *
 * Regression target: frontend/src/features/bim/BIMFilterPanel.tsx:864
 * — previous condition required `visibleElements < elements` to render the
 * action buttons, which hid them in the common "just grouped, no filter"
 * case.
 */
import { test, expect } from '@playwright/test';
import { loginV19, firstProjectId, firstBimModelId } from './helpers-v19';

test.describe('v1.9 #18 — BIM Type Name grouping reveals link buttons', () => {
  test.beforeEach(async ({ page }) => {
    await loginV19(page);
  });

  test('Link-to-BOQ button is rendered when any elements are visible', async ({ page }) => {
    const projectId = await firstProjectId(page);
    test.skip(!projectId, 'no project available for this test user');

    const modelId = await firstBimModelId(page, projectId!);
    test.skip(!modelId, 'no BIM model available — upload one to /bim first');

    await page.goto(`/bim/${modelId}`);
    await page.waitForLoadState('networkidle');

    // The filter panel's quick-takeoff button is labelled "Link N to BOQ"
    // (i18n key bim.quick_takeoff, with {{count}}). It should be present
    // the moment elements are loaded — grouping need not be toggled.
    const linkBtn = page.locator('button', { hasText: /Link\s+\d+\s+to\s+BOQ/i });

    await expect(linkBtn).toBeVisible({ timeout: 15_000 });
  });
});
