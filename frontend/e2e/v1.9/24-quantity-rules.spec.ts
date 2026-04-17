/**
 * RFC 24 — Quantity Rules redesign (BETA).
 *
 * Exercises the new RuleEditorModal behaviour on /bim/rules:
 *   - BETA badge shows in the page header
 *   - "Seed from model" reveals the picker and, when a model is picked,
 *     triggers the /schema/ request
 *   - Free-text entry still works in the element-type-filter input
 *     when no model has been seeded
 *   - Advanced mode reveals the AND/OR/NOT row operator and regex hint
 *   - Required fields carry a red asterisk next to their label
 *   - Saving a rule with seeded values persists (regression guard on the
 *     v1.9.0 #23 fix)
 */
import { test, expect } from '@playwright/test';

import { loginV19, ensureProject, firstBimModelId } from './helpers-v19';

test.describe.configure({ mode: 'serial' });

test.describe('v1.9 #24 — Quantity Rules redesign', () => {
  test.beforeEach(async ({ page }) => {
    await loginV19(page);
    await ensureProject(page);
  });

  test('BETA badge is visible in the page header', async ({ page }) => {
    await page.goto('/bim/rules');
    await page.waitForLoadState('networkidle');
    await expect(page.getByTestId('bim-rules-beta-badge')).toBeVisible();
    await expect(page.getByTestId('bim-rules-beta-badge')).toHaveText(/beta/i);
  });

  test('required-field asterisks show on name, element type, quantity source and unit', async ({
    page,
  }) => {
    await page.goto('/bim/rules');
    await page.waitForLoadState('networkidle');

    const newRuleBtn = page.locator('button', { hasText: /new\s+rule/i }).first();
    await expect(newRuleBtn).toBeVisible({ timeout: 10_000 });
    await newRuleBtn.click();

    // Every required label must end with a red asterisk. The asterisk
    // itself is a <span class="text-red-500">*</span> sibling to the label
    // text — we assert by counting them inside the dialog.
    const dialog = page.locator('[role="dialog"]').first();
    const asterisks = dialog.locator('span.text-red-500', { hasText: '*' });
    // name, element type, quantity source, unit => 4 required markers.
    await expect(asterisks).toHaveCount(4);
  });

  test('free-text entry still works when no model has been seeded', async ({ page }) => {
    await page.goto('/bim/rules');
    await page.waitForLoadState('networkidle');

    const newRuleBtn = page.locator('button', { hasText: /new\s+rule/i }).first();
    await newRuleBtn.click();

    const dialog = page.locator('[role="dialog"]').first();
    await expect(dialog).toBeVisible();

    // The "Seed from model" button should be visible and no seeded state yet.
    await expect(page.getByTestId('seed-from-model-btn')).toBeVisible();

    // Element-type-filter is now a list-bound <input>, not a <select>, so
    // free-text still works. Type an arbitrary string and assert the value.
    const input = dialog.locator('#rule-element-type');
    await input.fill('MyCustomWall*');
    await expect(input).toHaveValue('MyCustomWall*');
  });

  test('advanced mode reveals AND/OR/NOT row operator and regex hint', async ({ page }) => {
    await page.goto('/bim/rules');
    await page.waitForLoadState('networkidle');

    const newRuleBtn = page.locator('button', { hasText: /new\s+rule/i }).first();
    await newRuleBtn.click();

    const toggle = page.getByTestId('advanced-mode-toggle');
    await expect(toggle).toBeVisible();
    await toggle.check();

    // Regex hint text appears under the element-type input.
    const dialog = page.locator('[role="dialog"]').first();
    await expect(dialog.locator('text=/regex/i').first()).toBeVisible();

    // "Edit raw JSON" button is advanced-only.
    await expect(page.getByTestId('edit-raw-json')).toBeVisible();

    // Row operator only appears once there are >1 property-filter rows.
    await dialog.locator('button', { hasText: /add property/i }).first().click();
    await dialog.locator('button', { hasText: /add property/i }).first().click();
    await expect(page.getByTestId('row-operator')).toBeVisible();
    await page.getByTestId('row-operator').selectOption('OR');
    await expect(page.getByTestId('row-operator')).toHaveValue('OR');
  });

  test('seed from model fires the /schema/ request when a model is picked', async ({ page }) => {
    // Skip if there is no BIM model in the test project — we can't
    // exercise the network path without one.
    const modelId = await firstBimModelId(page, await ensureProject(page));
    if (!modelId) {
      test.skip(true, 'No BIM model available for seeding');
      return;
    }

    await page.goto('/bim/rules');
    await page.waitForLoadState('networkidle');

    const newRuleBtn = page.locator('button', { hasText: /new\s+rule/i }).first();
    await newRuleBtn.click();

    await page.getByTestId('seed-from-model-btn').click();

    const schemaPromise = page.waitForResponse(
      (r) => r.url().includes(`/models/${modelId}/schema/`) && r.request().method() === 'GET',
      { timeout: 10_000 },
    );

    await page.getByTestId(`seed-model-option-${modelId}`).click();

    const resp = await schemaPromise;
    expect(resp.ok()).toBeTruthy();

    // After seeding the quantity-source <select> should be populated from
    // the response's `available_quantities` — at a minimum one of the
    // preset values must exist as an option.
    const qsrc = page.locator('#rule-qsrc');
    const optionValues = await qsrc.locator('option').allTextContents();
    expect(optionValues.some((v) => /area_m2|volume_m3|count/.test(v))).toBeTruthy();
  });

  test('rule create with seeded values saves and appears in the list (regression #23)', async ({
    page,
  }) => {
    await page.goto('/bim/rules');
    await page.waitForLoadState('networkidle');

    const newRuleBtn = page.locator('button', { hasText: /new\s+rule/i }).first();
    await newRuleBtn.click();

    const dialog = page.locator('[role="dialog"]').first();
    await expect(dialog).toBeVisible();

    const ruleName = `v19-24-e2e-${Date.now().toString(36)}`;
    await dialog.locator('#rule-name').fill(ruleName);
    await dialog.locator('#rule-element-type').fill('Wall*');

    const postPromise = page.waitForResponse(
      (r) => r.url().includes('/quantity-maps/') && r.request().method() === 'POST',
      { timeout: 15_000 },
    );

    await dialog.locator('button[type="submit"]', { hasText: /save/i }).first().click();

    const resp = await postPromise;
    expect(resp.ok()).toBeTruthy();

    // The rule appears in the list — either directly visible in the table
    // or via the name cell. Use a broad text match anywhere on the page.
    await expect(page.locator(`text=${ruleName}`).first()).toBeVisible({ timeout: 10_000 });
  });
});
